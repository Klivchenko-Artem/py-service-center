"""Фикстуры: клиент с техникой, мастер, приёмщик."""

from __future__ import annotations

import datetime as dt

import pytest
from django.contrib.auth.models import Group, Permission, User
from django.utils import timezone

from service.models import Client, Device, Ticket


@pytest.fixture
def client_record(db) -> Client:
    return Client.objects.create(full_name="Пётр Петров", phone="+79990000001")


@pytest.fixture
def device(client_record: Client) -> Device:
    return Device.objects.create(
        client=client_record, kind="Ноутбук", model="Lenovo IdeaPad", serial_number="SN-1"
    )


@pytest.fixture
def master(db) -> User:
    """Мастер: видит только свои заявки, закрывать их не может."""
    user = User.objects.create_user("master", password="stand-password", is_staff=True)
    group = Group.objects.create(name="Мастера")
    group.permissions.set(
        Permission.objects.filter(
            codename__in=["view_ticket", "change_ticket", "add_comment", "view_comment"]
        )
    )
    user.groups.add(group)

    return user


@pytest.fixture
def manager(db) -> User:
    """Приёмщик: видит все заявки и умеет их закрывать."""
    user = User.objects.create_user("manager", password="stand-password", is_staff=True)
    group = Group.objects.create(name="Приёмщики")
    group.permissions.set(
        Permission.objects.filter(
            codename__in=[
                "view_ticket",
                "change_ticket",
                "add_ticket",
                "view_all_tickets",
                "close_ticket",
                "view_comment",
                "add_comment",
            ]
        )
    )
    user.groups.add(group)

    return user


@pytest.fixture
def ticket(client_record: Client, device: Device) -> Ticket:
    return Ticket.objects.create(
        client=client_record,
        device=device,
        problem="не включается",
        deadline=timezone.localdate() + dt.timedelta(days=3),
    )
