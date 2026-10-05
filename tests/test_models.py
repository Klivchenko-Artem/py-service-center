"""Правила самих заявок: номер, закрытие, просрочка, видимость."""

from __future__ import annotations

import datetime as dt

from django.contrib.auth.models import User
from django.utils import timezone

from service.models import Client, Device, Ticket


def test_number_is_generated_in_order(client_record: Client, device: Device) -> None:
    first = Ticket.objects.create(client=client_record, device=device, problem="раз")
    second = Ticket.objects.create(client=client_record, device=device, problem="два")

    year = timezone.localdate().year % 100

    assert first.number == f"{year:02d}-0001"
    assert second.number == f"{year:02d}-0002"


def test_closed_at_is_set_and_cleared(ticket: Ticket) -> None:
    ticket.status = Ticket.Status.DONE
    ticket.save()
    ticket.refresh_from_db()

    # Дату закрытия руками не ставят, по ней считается срок ремонта
    assert ticket.closed_at is not None

    ticket.status = Ticket.Status.IN_PROGRESS
    ticket.save()
    ticket.refresh_from_db()

    # Заявку вернули в работу, значит она снова открыта
    assert ticket.closed_at is None


def test_overdue_only_for_open_tickets(ticket: Ticket) -> None:
    ticket.deadline = timezone.localdate() - dt.timedelta(days=1)
    ticket.save()

    assert ticket.is_overdue is True
    assert Ticket.objects.overdue().count() == 1

    ticket.status = Ticket.Status.DONE
    ticket.save()

    # Закрытая заявка не просрочена: чинить в ней уже нечего
    assert ticket.is_overdue is False
    assert Ticket.objects.overdue().count() == 0


def test_master_sees_only_own_tickets(
    client_record: Client, device: Device, master: User, manager: User
) -> None:
    mine = Ticket.objects.create(
        client=client_record, device=device, problem="моя", assignee=master
    )
    Ticket.objects.create(client=client_record, device=device, problem="чужая", assignee=manager)

    visible = Ticket.objects.for_user(master)

    assert list(visible) == [mine]


def test_master_sees_unassigned_tickets(
    client_record: Client, device: Device, master: User
) -> None:
    free = Ticket.objects.create(client=client_record, device=device, problem="ничья")

    # Свободную заявку должен видеть каждый мастер, иначе её некому взять
    assert list(Ticket.objects.for_user(master)) == [free]


def test_manager_sees_everything(
    client_record: Client, device: Device, master: User, manager: User
) -> None:
    Ticket.objects.create(client=client_record, device=device, problem="раз", assignee=master)
    Ticket.objects.create(client=client_record, device=device, problem="два", assignee=manager)

    assert Ticket.objects.for_user(manager).count() == 2


def test_open_queryset_excludes_finished(client_record: Client, device: Device) -> None:
    Ticket.objects.create(client=client_record, device=device, problem="раз")
    Ticket.objects.create(
        client=client_record, device=device, problem="два", status=Ticket.Status.DONE
    )
    Ticket.objects.create(
        client=client_record, device=device, problem="три", status=Ticket.Status.REJECTED
    )

    assert Ticket.objects.open().count() == 1
