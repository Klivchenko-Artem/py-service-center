"""Наполняет стенд: группы прав, сотрудники и десяток заявок.

Пустая админка ничего не рассказывает о проекте: и права, и фильтры, и цветные
статусы видно только на данных.
"""

from __future__ import annotations

import datetime as dt
import random

from django.contrib.auth.models import Group, Permission, User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from service.models import Client, Comment, Device, Ticket

MASTER_PERMISSIONS = ["view_ticket", "change_ticket", "add_comment", "view_comment"]
MANAGER_PERMISSIONS = [
    *MASTER_PERMISSIONS,
    "add_ticket",
    "delete_ticket",
    "view_all_tickets",
    "close_ticket",
    "add_client",
    "change_client",
    "view_client",
    "add_device",
    "change_device",
    "view_device",
]

DEVICES = [
    ("Ноутбук", "Lenovo IdeaPad 3"),
    ("Телевизор", "Samsung UE43"),
    ("Смартфон", "Xiaomi Redmi Note 12"),
    ("Стиральная машина", "Bosch WLG 20"),
    ("Микроволновка", "LG MS-2042"),
]

PROBLEMS = [
    "не включается после скачка напряжения",
    "шумит вентилятор, греется корпус",
    "разбит экран, нужна замена",
    "не держит зарядку",
    "течёт вода при отжиме",
]


class Command(BaseCommand):
    help = "Заводит группы прав, сотрудников и демонстрационные заявки"

    def add_arguments(self, parser) -> None:
        parser.add_argument("--tickets", type=int, default=12, help="сколько заявок завести")

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        masters = self._group("Мастера", MASTER_PERMISSIONS)
        managers = self._group("Приёмщики", MANAGER_PERMISSIONS)

        master = self._staff("master", "Мастер Петров", masters)
        manager = self._staff("manager", "Приёмщик Иванова", managers)

        random.seed(20260909)
        today = timezone.localdate()

        for index in range(options["tickets"]):
            client, _ = Client.objects.get_or_create(
                phone=f"+7999000{index:04d}",
                defaults={"full_name": f"Клиент №{index + 1}", "email": ""},
            )

            kind, model = DEVICES[index % len(DEVICES)]
            device, _ = Device.objects.get_or_create(
                client=client, kind=kind, model=model, serial_number=f"SN{index:06d}"
            )

            status = random.choice(list(Ticket.Status))
            ticket = Ticket.objects.create(
                client=client,
                device=device,
                problem=PROBLEMS[index % len(PROBLEMS)],
                status=status,
                priority=random.choice(list(Ticket.Priority)),
                assignee=master if index % 2 else manager,
                price=random.choice([None, 1500, 3200, 7800]),
                # Часть заявок намеренно просрочена: иначе не видно ни фильтра
                # «просрочены», ни красной даты в списке
                deadline=today + dt.timedelta(days=random.choice([-5, -1, 2, 7])),
            )

            if index % 3 == 0:
                Comment.objects.create(
                    ticket=ticket,
                    author=master,
                    text="Разобрал, нужна запчасть. Заказал, ждём поставку.",
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Готово. Заявок: {Ticket.objects.count()}. "
                "Сотрудники: master / manager, пароль stand-password."
            )
        )

    def _group(self, name: str, codenames: list[str]) -> Group:
        group, _ = Group.objects.get_or_create(name=name)
        group.permissions.set(Permission.objects.filter(codename__in=codenames))

        return group

    def _staff(self, username: str, full_name: str, group: Group) -> User:
        user, created = User.objects.get_or_create(
            username=username,
            defaults={"first_name": full_name, "is_staff": True},
        )

        if created:
            # Пароль стендовый и напечатан в подсказке: секретов в репозитории нет
            user.set_password("stand-password")
            user.save(update_fields=["password"])

        user.groups.add(group)

        return user
