"""Модели сервисного центра: клиенты, устройства, заявки, комментарии."""

from __future__ import annotations

import datetime as dt

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models.functions import Length, Substr
from django.utils import timezone


class Client(models.Model):
    """Тот, кто принёс технику."""

    full_name = models.CharField("ФИО", max_length=150)
    phone = models.CharField("Телефон", max_length=20, unique=True)
    email = models.EmailField("Почта", blank=True)
    created_at = models.DateTimeField("Заведён", auto_now_add=True)

    class Meta:
        verbose_name = "клиент"
        verbose_name_plural = "клиенты"
        ordering = ["full_name"]

    def __str__(self) -> str:
        return f"{self.full_name} ({self.phone})"


class Device(models.Model):
    """Конкретный аппарат конкретного клиента."""

    client = models.ForeignKey(
        Client, verbose_name="клиент", on_delete=models.CASCADE, related_name="devices"
    )
    kind = models.CharField("Тип", max_length=50)
    model = models.CharField("Модель", max_length=100)
    serial_number = models.CharField("Серийный номер", max_length=64, blank=True)

    class Meta:
        verbose_name = "устройство"
        verbose_name_plural = "устройства"
        constraints = [
            # Пустой серийник это обычное дело (стёрся, нет наклейки), а вот два
            # одинаковых непустых означают, что аппарат завели дважды
            models.UniqueConstraint(
                fields=["serial_number"],
                condition=~models.Q(serial_number=""),
                name="uq_device_serial_number",
            )
        ]

    def __str__(self) -> str:
        return f"{self.kind} {self.model}".strip()


class TicketQuerySet(models.QuerySet):
    def open(self) -> TicketQuerySet:
        return self.exclude(status__in=[Ticket.Status.DONE, Ticket.Status.REJECTED])

    def overdue(self) -> TicketQuerySet:
        # localdate, а не now().date(): второй считает в UTC, и с полуночи
        # до трёх ночи по Москве счётчик расходился с подсветкой в таблице,
        # которая смотрит на is_overdue
        return self.open().filter(deadline__lt=timezone.localdate())

    def for_user(self, user) -> TicketQuerySet:
        """Мастер видит свои заявки и ничьи, приёмщик и начальство видят все.

        Ничьи нужны, чтобы мастеру было что брать в работу: иначе новая заявка
        не видна никому, кроме приёмщика. Права проверяются здесь, а не
        в шаблоне: одно правило работает и в админке, и в тестах.
        """
        if user.is_superuser or user.has_perm("service.view_all_tickets"):
            return self

        return self.filter(models.Q(assignee=user) | models.Q(assignee__isnull=True))


class Ticket(models.Model):
    """Заявка на ремонт."""

    class Status(models.TextChoices):
        NEW = "new", "Новая"
        IN_PROGRESS = "in_progress", "В работе"
        WAITING_PARTS = "waiting_parts", "Ждёт запчасть"
        DONE = "done", "Готова"
        REJECTED = "rejected", "Отказ"

    class Priority(models.IntegerChoices):
        LOW = 1, "Низкий"
        NORMAL = 2, "Обычный"
        HIGH = 3, "Срочно"

    number = models.CharField("Номер", max_length=12, unique=True, editable=False)
    client = models.ForeignKey(
        Client, verbose_name="клиент", on_delete=models.PROTECT, related_name="tickets"
    )
    device = models.ForeignKey(
        Device, verbose_name="устройство", on_delete=models.PROTECT, related_name="tickets"
    )
    problem = models.TextField("Что случилось")
    status = models.CharField(
        "Статус", max_length=20, choices=Status.choices, default=Status.NEW, db_index=True
    )
    priority = models.IntegerField(
        "Приоритет", choices=Priority.choices, default=Priority.NORMAL
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="мастер",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tickets",
    )
    price = models.DecimalField(
        "Стоимость",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    deadline = models.DateField("Срок", null=True, blank=True)
    created_at = models.DateTimeField("Создана", auto_now_add=True)
    updated_at = models.DateTimeField("Изменена", auto_now=True)
    closed_at = models.DateTimeField("Закрыта", null=True, blank=True, editable=False)

    objects = TicketQuerySet.as_manager()

    class Meta:
        verbose_name = "заявка"
        verbose_name_plural = "заявки"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "created_at"])]
        permissions = [
            ("view_all_tickets", "Видит заявки всех мастеров"),
            ("close_ticket", "Может закрывать заявки"),
        ]

    def __str__(self) -> str:
        return f"{self.number}, {self.device}"

    def save(self, *args, **kwargs) -> None:
        if not self.number:
            self.number = self._next_number()

        # Дата закрытия ставится сама: руками её забудут, а по ней считается
        # средний срок ремонта
        if self.status in {self.Status.DONE, self.Status.REJECTED} and self.closed_at is None:
            self.closed_at = timezone.now()

        if self.status not in {self.Status.DONE, self.Status.REJECTED}:
            self.closed_at = None

        super().save(*args, **kwargs)

    @property
    def is_open(self) -> bool:
        return self.status not in {self.Status.DONE, self.Status.REJECTED}

    @property
    def is_overdue(self) -> bool:
        return bool(self.deadline and self.is_open and self.deadline < timezone.localdate())

    @property
    def days_in_work(self) -> int:
        finished = self.closed_at or timezone.now()

        return (finished - self.created_at).days

    @classmethod
    def _next_number(cls) -> str:
        """Номер вида 26-0007: год и порядковый номер внутри года.

        Считаем в базе, а не в питоне: прочитать последний номер и прибавить
        единицу это гонка, при которой два одновременных посетителя получают
        один номер и второй ловит пятисотку на уникальном ключе.

        Сортировка по длине и только потом по строке: иначе после 26-9999
        «наибольшим» навсегда остаётся он, и счётчик встаёт намертво.
        """
        year = timezone.localdate().year
        prefix = f"{year % 100:02d}-"

        last = (
            cls.objects.filter(number__startswith=prefix)
            .annotate(tail=Substr("number", len(prefix) + 1))
            .annotate(tail_length=Length("tail"))
            .order_by("-tail_length", "-tail")
            .values_list("number", flat=True)
            .first()
        )

        counter = int(last.split("-")[1]) + 1 if last else 1

        # Пятизначный номер после 9999, не беда: ширина в формате задаёт
        # минимум, а не потолок
        return f"{prefix}{counter:04d}"


class Comment(models.Model):
    """Заметка мастера по заявке."""

    ticket = models.ForeignKey(
        Ticket, verbose_name="заявка", on_delete=models.CASCADE, related_name="comments"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="автор",
        on_delete=models.SET_NULL,
        null=True,
        related_name="comments",
    )
    text = models.TextField("Текст")
    created_at = models.DateTimeField("Добавлен", auto_now_add=True)

    class Meta:
        verbose_name = "комментарий"
        verbose_name_plural = "комментарии"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.ticket.number}: {self.text[:40]}"


def default_deadline(days: int = 3) -> dt.date:
    """Срок по умолчанию: три рабочих дня от сегодня."""
    return timezone.localdate() + dt.timedelta(days=days)
