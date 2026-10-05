"""Админка: видимость по правам, массовые действия, сводка."""

from __future__ import annotations

import pytest
from django.contrib.auth.models import User
from django.test import Client as HttpClient
from django.urls import reverse

from service.models import Client, Comment, Device, Ticket

CHANGELIST = reverse("admin:service_ticket_changelist")


@pytest.fixture
def as_master(master: User) -> HttpClient:
    http = HttpClient()
    http.force_login(master)

    return http


@pytest.fixture
def as_manager(manager: User) -> HttpClient:
    http = HttpClient()
    http.force_login(manager)

    return http


@pytest.mark.django_db
def test_master_sees_only_own_tickets(
    as_master: HttpClient, client_record: Client, device: Device, master: User, manager: User
) -> None:
    mine = Ticket.objects.create(
        client=client_record, device=device, problem="моя", assignee=master
    )
    foreign = Ticket.objects.create(
        client=client_record, device=device, problem="чужая", assignee=manager
    )

    page = as_master.get(CHANGELIST).content.decode()

    assert mine.number in page
    assert foreign.number not in page


@pytest.mark.django_db
def test_take_to_work_assigns_current_user(as_master: HttpClient, ticket: Ticket) -> None:
    as_master.post(
        CHANGELIST,
        {"action": "take_to_work", "_selected_action": [ticket.pk], "index": 0},
        follow=True,
    )

    ticket.refresh_from_db()

    assert ticket.status == Ticket.Status.IN_PROGRESS
    assert ticket.assignee.username == "master"


@pytest.mark.django_db
def test_master_cannot_close_tickets(as_master: HttpClient, ticket: Ticket, master: User) -> None:
    ticket.assignee = master
    ticket.save()

    response = as_master.post(
        CHANGELIST,
        {"action": "mark_done", "_selected_action": [ticket.pk], "index": 0},
        follow=True,
    )

    ticket.refresh_from_db()

    # Право закрывать есть не у всех: у мастера-стажёра его нет
    assert ticket.status != Ticket.Status.DONE
    assert "Нет права закрывать заявки" in response.content.decode()


@pytest.mark.django_db
def test_manager_closes_ticket(as_manager: HttpClient, ticket: Ticket) -> None:
    as_manager.post(
        CHANGELIST,
        {"action": "mark_done", "_selected_action": [ticket.pk], "index": 0},
        follow=True,
    )

    ticket.refresh_from_db()

    assert ticket.status == Ticket.Status.DONE
    assert ticket.closed_at is not None


@pytest.mark.django_db
def test_raise_priority(as_manager: HttpClient, ticket: Ticket) -> None:
    as_manager.post(
        CHANGELIST,
        {"action": "raise_priority", "_selected_action": [ticket.pk], "index": 0},
        follow=True,
    )

    ticket.refresh_from_db()

    assert ticket.priority == Ticket.Priority.HIGH


@pytest.mark.django_db
def test_comment_author_is_filled_from_request(
    as_manager: HttpClient, ticket: Ticket, manager: User
) -> None:
    url = reverse("admin:service_ticket_change", args=[ticket.pk])

    as_manager.post(
        url,
        {
            "client": ticket.client_id,
            "device": ticket.device_id,
            "problem": ticket.problem,
            "status": ticket.status,
            "priority": ticket.priority,
            "assignee": "",
            "price": "",
            "deadline": "",
            "comments-TOTAL_FORMS": "1",
            "comments-INITIAL_FORMS": "0",
            "comments-MIN_NUM_FORMS": "0",
            "comments-MAX_NUM_FORMS": "1000",
            "comments-0-text": "Разобрал, нужна запчасть",
            "comments-0-id": "",
            "comments-0-ticket": ticket.pk,
        },
        follow=True,
    )

    comment = Comment.objects.get()

    # Автора не выбирают руками: его подставляет админка
    assert comment.author_id == manager.pk


@pytest.mark.django_db
def test_changelist_shows_summary(as_manager: HttpClient, ticket: Ticket) -> None:
    """Над списком заявок висит сводка: открытые, просроченные, средний чек.

    Проверять надо сами числа: слова «В работе» и «просрочено» есть и в подписях
    фильтров сбоку, поэтому прежний ассерт проходил даже без сводки.
    """
    response = as_manager.get(CHANGELIST)
    summary = response.context["summary"]

    assert summary["open"] == 1
    assert summary["overdue"] == 0

    ticket.status = Ticket.Status.DONE
    ticket.price = 1500
    ticket.save()

    summary = as_manager.get(CHANGELIST).context["summary"]

    assert summary["open"] == 0
    assert summary["avg_price"] == 1500


@pytest.mark.django_db
def test_overdue_filter(
    as_manager: HttpClient, client_record: Client, device: Device
) -> None:
    import datetime as dt

    from django.utils import timezone

    late = Ticket.objects.create(
        client=client_record,
        device=device,
        problem="просрочена",
        deadline=timezone.localdate() - dt.timedelta(days=2),
    )
    on_time = Ticket.objects.create(
        client=client_record,
        device=device,
        problem="в срок",
        deadline=timezone.localdate() + dt.timedelta(days=5),
    )

    page = as_manager.get(CHANGELIST, {"overdue": "yes"}).content.decode()

    assert late.number in page
    assert on_time.number not in page


@pytest.mark.django_db
def test_master_cannot_close_ticket_through_form(
    as_master: HttpClient, master: User, ticket: Ticket
) -> None:
    """Право close_ticket проверялось только в массовом действии.

    Через обычную форму редактирования статус «Готова» ставил любой,
    у кого есть change_ticket, то есть каждый мастер.
    """
    ticket.assignee = master
    ticket.save(update_fields=["assignee"])

    url = reverse("admin:service_ticket_change", args=[ticket.pk])
    response = as_master.get(url)
    form = response.context["adminform"].form

    statuses = [value for value, _ in form.fields["status"].choices]

    assert Ticket.Status.DONE not in statuses
    assert Ticket.Status.REJECTED not in statuses
    assert Ticket.Status.IN_PROGRESS in statuses


@pytest.mark.django_db
def test_manager_can_close_ticket_through_form(as_manager: HttpClient, ticket: Ticket) -> None:
    url = reverse("admin:service_ticket_change", args=[ticket.pk])
    form = as_manager.get(url).context["adminform"].form

    statuses = [value for value, _ in form.fields["status"].choices]

    assert Ticket.Status.DONE in statuses


@pytest.mark.django_db
def test_master_does_not_see_comments_on_foreign_tickets(
    as_master: HttpClient, master: User, manager: User, ticket: Ticket
) -> None:
    """Чужие заявки мастеру скрыты, а переписка по ним, была видна.

    В комментариях лежат диагноз и цена, то есть ровно то, что и прячут.
    """
    # Заявка занята другим мастером, для нашего она чужая. Ничьи заявки
    # мастеру видны намеренно: иначе ему нечего было бы брать в работу
    ticket.assignee = manager
    ticket.save(update_fields=["assignee"])

    Comment.objects.create(ticket=ticket, author=manager, text="диагноз: сгорел контроллер")

    response = as_master.get(reverse("admin:service_comment_changelist"))

    assert response.status_code == 200
    assert response.context["cl"].result_count == 0

    # А свою заявку мастер видит вместе с перепиской
    ticket.assignee = master
    ticket.save(update_fields=["assignee"])

    response = as_master.get(reverse("admin:service_comment_changelist"))

    assert response.context["cl"].result_count == 1


@pytest.mark.django_db
def test_take_to_work_leaves_closed_alone(as_manager: HttpClient, ticket: Ticket) -> None:
    """«Взять в работу» должно сбрасывать дату закрытия.

    С update_fields до базы доезжает только перечисленное, поэтому closed_at
    оставался от прошлого закрытия, и срок ремонта считался неверно.
    """
    ticket.status = Ticket.Status.DONE
    ticket.save()
    ticket.refresh_from_db()

    assert ticket.closed_at is not None

    as_manager.post(
        reverse("admin:service_ticket_changelist"),
        {"action": "take_to_work", "_selected_action": [str(ticket.pk)], "index": "0"},
    )

    ticket.refresh_from_db()

    # Закрытую заявку действие трогать не должно вовсе
    assert ticket.status == Ticket.Status.DONE
    assert ticket.closed_at is not None
