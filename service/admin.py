"""Админка сервисного центра.

Основная работа приёмщика и мастера идёт здесь, поэтому админка не оставлена
в состоянии «зарегистрировал модель и ладно»: колонки, фильтры, массовые
действия и ограничение видимости по правам.
"""

from __future__ import annotations

from django.contrib import admin, messages
from django.db.models import Avg, Count, QuerySet
from django.http import HttpRequest
from django.utils import timezone
from django.utils.html import format_html

from service.models import Client, Comment, Device, Ticket


class DeviceInline(admin.TabularInline):
    model = Device
    extra = 0
    fields = ("kind", "model", "serial_number")


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("full_name", "phone", "email", "device_count", "ticket_count")
    search_fields = ("full_name", "phone", "email")
    inlines = [DeviceInline]

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        # Счётчики считает база: иначе список клиентов делает по два запроса
        # на каждую строку
        return (
            super()
            .get_queryset(request)
            .annotate(devices_total=Count("devices", distinct=True))
            .annotate(tickets_total=Count("tickets", distinct=True))
        )

    @admin.display(description="Устройств", ordering="devices_total")
    def device_count(self, client: Client) -> int:
        return client.devices_total

    @admin.display(description="Заявок", ordering="tickets_total")
    def ticket_count(self, client: Client) -> int:
        return client.tickets_total


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ("__str__", "client", "serial_number")
    list_select_related = ("client",)
    search_fields = ("model", "serial_number", "client__full_name")
    autocomplete_fields = ("client",)


class CommentInline(admin.TabularInline):
    model = Comment
    extra = 1
    fields = ("text", "author", "created_at")
    readonly_fields = ("author", "created_at")


class OverdueFilter(admin.SimpleListFilter):
    """Фильтр «просроченные» для того, чего нет среди полей."""

    title = "срок"
    parameter_name = "overdue"

    def lookups(self, request: HttpRequest, model_admin) -> list[tuple[str, str]]:
        return [("yes", "Просрочены"), ("no", "В срок")]

    def queryset(self, request: HttpRequest, queryset: QuerySet) -> QuerySet:
        if self.value() == "yes":
            return queryset.overdue()

        if self.value() == "no":
            return queryset.exclude(pk__in=queryset.model.objects.overdue())

        return queryset


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = (
        "number",
        "client",
        "device",
        "status_badge",
        "priority",
        "assignee",
        "deadline_cell",
        "price",
    )
    list_display_links = ("number",)
    list_filter = ("status", "priority", OverdueFilter, "assignee")
    list_select_related = ("client", "device", "assignee")
    search_fields = ("number", "client__full_name", "client__phone", "device__model", "problem")
    # assignee здесь нет намеренно: автодополнение по пользователям требует
    # auth.view_user, которого у мастера нет, и поле у него просто не работало.
    # Обычный выпадающий список работает у всех
    autocomplete_fields = ("client", "device")
    date_hierarchy = "created_at"
    readonly_fields = ("number", "created_at", "updated_at", "closed_at", "days_in_work")
    inlines = [CommentInline]
    actions = ["take_to_work", "mark_done", "raise_priority"]
    list_per_page = 50

    fieldsets = (
        ("Заявка", {"fields": ("number", "client", "device", "problem")}),
        ("Работа", {"fields": ("status", "priority", "assignee", "price", "deadline")}),
        (
            "Даты",
            {
                "fields": ("created_at", "updated_at", "closed_at", "days_in_work"),
                "classes": ("collapse",),
            },
        ),
    )

    #: Статусы, ставить которые вправе не каждый: закрытие заявки
    #: это конец работы и деньги, у мастера-стажёра такого права нет.
    CLOSING_STATUSES = (Ticket.Status.DONE, Ticket.Status.REJECTED)

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        # Мастер видит только свои заявки, правило живёт в менеджере модели
        return super().get_queryset(request).for_user(request.user)

    def get_form(self, request: HttpRequest, obj=None, change=False, **kwargs):
        """Убирает закрывающие статусы у тех, кому закрывать не положено.

        Право close_ticket проверялось только в массовом действии, а через
        обычную форму редактирования статус «Готова» ставил любой, у кого есть
        change_ticket. Форма и действие должны слушаться одного правила.
        """
        form = super().get_form(request, obj, change=change, **kwargs)

        if not request.user.has_perm("service.close_ticket") and "status" in form.base_fields:
            field = form.base_fields["status"]
            allowed = [
                (value, label)
                for value, label in Ticket.Status.choices
                if value not in self.CLOSING_STATUSES
            ]

            # Заявку, уже закрытую кем-то другим, из списка выкидывать нельзя:
            # иначе её не сохранить вообще
            if obj is not None and obj.status in self.CLOSING_STATUSES:
                allowed.append((obj.status, obj.get_status_display()))

            field.choices = allowed

        return form

    @admin.display(description="Статус", ordering="status")
    def status_badge(self, ticket: Ticket) -> str:
        colors = {
            Ticket.Status.NEW: "#0b6bcb",
            Ticket.Status.IN_PROGRESS: "#b26a00",
            Ticket.Status.WAITING_PARTS: "#7b1fa2",
            Ticket.Status.DONE: "#2e7d32",
            Ticket.Status.REJECTED: "#757575",
        }

        return format_html(
            '<b style="color: {}">{}</b>', colors[ticket.status], ticket.get_status_display()
        )

    @admin.display(description="Срок", ordering="deadline")
    def deadline_cell(self, ticket: Ticket) -> str:
        if not ticket.deadline:
            return "-"

        if ticket.is_overdue:
            return format_html('<span style="color: #c62828">{}</span>', ticket.deadline)

        return str(ticket.deadline)

    def save_formset(self, request: HttpRequest, form, formset, change) -> None:
        """Автор комментария проставляется сам, руками его выбирать незачем."""
        instances = formset.save(commit=False)

        for instance in instances:
            if isinstance(instance, Comment) and instance.author_id is None:
                instance.author = request.user

            instance.save()

        formset.save_m2m()

        for obj in formset.deleted_objects:
            obj.delete()

    @admin.action(description="Взять в работу")
    def take_to_work(self, request: HttpRequest, queryset: QuerySet) -> None:
        updated = 0

        # exclude по одному DONE пропускал отклонённые: заявку, которую уже
        # завернули, действие поднимало обратно в работу
        for ticket in queryset.exclude(status__in=self.CLOSING_STATUSES):
            ticket.status = Ticket.Status.IN_PROGRESS
            ticket.assignee = ticket.assignee or request.user

            # closed_at сбрасывается в save(), но с update_fields до базы
            # доезжает только перечисленное, поэтому поле в списке
            ticket.save(update_fields=["status", "assignee", "closed_at", "updated_at"])
            updated += 1

        self.message_user(request, f"Взято в работу: {updated}", messages.SUCCESS)

    @admin.action(description="Отметить готовыми")
    def mark_done(self, request: HttpRequest, queryset: QuerySet) -> None:
        # Закрывать заявки может не каждый: у мастера-стажёра такого права нет
        if not request.user.has_perm("service.close_ticket"):
            self.message_user(request, "Нет права закрывать заявки", messages.ERROR)

            return

        updated = 0

        for ticket in queryset.exclude(status__in=self.CLOSING_STATUSES):
            ticket.status = Ticket.Status.DONE
            ticket.closed_at = timezone.now()
            ticket.save(update_fields=["status", "closed_at", "updated_at"])
            updated += 1

        self.message_user(request, f"Закрыто заявок: {updated}", messages.SUCCESS)

    @admin.action(description="Поднять приоритет")
    def raise_priority(self, request: HttpRequest, queryset: QuerySet) -> None:
        updated = 0

        # Через .update() было бы одним запросом, но auto_now у updated_at
        # при этом не срабатывает: в списке заявок стояло бы старое время,
        # и по нему нельзя было бы понять, когда заявку последний раз трогали
        for ticket in queryset.filter(priority__lt=Ticket.Priority.HIGH):
            ticket.priority = Ticket.Priority.HIGH
            ticket.save(update_fields=["priority", "updated_at"])
            updated += 1

        self.message_user(request, f"Срочных стало больше на {updated}", messages.SUCCESS)

    def changelist_view(self, request: HttpRequest, extra_context: dict | None = None):
        """Над списком заявок висит короткая сводка, она нужна каждый день."""
        tickets = self.get_queryset(request)

        extra_context = extra_context or {}
        extra_context["summary"] = {
            "open": tickets.open().count(),
            "overdue": tickets.overdue().count(),
            "avg_price": tickets.filter(price__isnull=False).aggregate(value=Avg("price"))["value"],
        }

        return super().changelist_view(request, extra_context)


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("ticket", "author", "created_at")
    list_select_related = ("ticket", "author")
    search_fields = ("text", "ticket__number")
    readonly_fields = ("created_at",)

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        """Комментарии видны по тем же правилам, что и сами заявки.

        Без этого мастеру, которому выдано view_comment, чужие заявки были
        не видны, а вся переписка по ним, вполне: и диагноз, и цена.
        """
        tickets = Ticket.objects.for_user(request.user)

        return super().get_queryset(request).filter(ticket__in=tickets)


admin.site.site_header = "Сервисный центр"
admin.site.site_title = "Сервисный центр"
admin.site.index_title = "Заявки и клиенты"
