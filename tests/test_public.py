"""Публичная часть: подача заявки и проверка статуса."""

from __future__ import annotations

import pytest
from django.test import Client as HttpClient
from django.urls import reverse

from service.forms import TicketRequestForm
from service.models import Client, Ticket

FORM = {
    "full_name": "Пётр Петров",
    "phone": "8 (999) 000-00-01",
    "email": "",
    "kind": "Ноутбук",
    "model": "Lenovo IdeaPad",
    "serial_number": "SN-1",
    "problem": "не включается",
}


@pytest.mark.django_db
def test_phone_is_normalized() -> None:
    form = TicketRequestForm(FORM)

    assert form.is_valid()
    # Телефон приводится к одному виду: по нему ищется постоянный клиент
    assert form.cleaned_data["phone"] == "+79990000001"


@pytest.mark.django_db
def test_short_phone_rejected() -> None:
    form = TicketRequestForm({**FORM, "phone": "12345"})

    assert not form.is_valid()
    assert "phone" in form.errors


@pytest.mark.django_db
def test_second_ticket_reuses_client(http_client: HttpClient) -> None:
    http_client.post(reverse("service:create_ticket"), FORM)
    http_client.post(reverse("service:create_ticket"), {**FORM, "problem": "не заряжается"})

    # Тот же телефон, тот же клиент, а не второй с той же фамилией
    assert Client.objects.count() == 1
    assert Ticket.objects.count() == 2


@pytest.mark.django_db
def test_create_redirects_to_number(http_client: HttpClient) -> None:
    response = http_client.post(reverse("service:create_ticket"), FORM)

    ticket = Ticket.objects.get()

    # Редирект после отправки: обновление страницы не должно заводить дубль
    assert response.status_code == 302
    assert response.url == reverse("service:ticket_created", args=[ticket.number])


@pytest.mark.django_db
def test_status_needs_matching_phone(http_client: HttpClient, ticket: Ticket) -> None:
    right = http_client.post(
        reverse("service:ticket_status"), {"number": ticket.number, "phone": "+79990000001"}
    )
    wrong = http_client.post(
        reverse("service:ticket_status"), {"number": ticket.number, "phone": "+79995555555"}
    )

    # По одному номеру чужую заявку не посмотреть: номера идут подряд
    assert ticket.number in right.content.decode()
    assert wrong.context["not_found"] is True


@pytest.mark.django_db
def test_dashboard_counts(http_client: HttpClient, ticket: Ticket) -> None:
    response = http_client.get(reverse("service:dashboard"))

    assert response.status_code == 200
    assert response.context["stats"]["open"] == 1


@pytest.fixture
def http_client() -> HttpClient:
    return HttpClient()


@pytest.mark.django_db
def test_created_page_is_only_for_its_author(http_client: HttpClient) -> None:
    """Страница «заявка принята» не должна отдавать чужую заявку по номеру.

    Номера идут подряд (26-0001, 26-0002...), так что без этой проверки вся
    база ремонтов вместе с телефонами выкачивалась циклом curl.
    """
    http_client.post(reverse("service:create_ticket"), FORM)
    ticket = Ticket.objects.get()

    url = reverse("service:ticket_created", kwargs={"number": ticket.number})

    # Тому, кто подал заявку, страница видна: номер лежит у него в сессии
    assert http_client.get(url).status_code == 200

    # Постороннему нельзя, даже если он знает номер
    assert HttpClient().get(url).status_code == 404


@pytest.mark.django_db
def test_anonymous_form_does_not_overwrite_client_card(http_client: HttpClient) -> None:
    """Знание чужого телефона не должно давать права переписать карточку."""
    http_client.post(reverse("service:create_ticket"), {**FORM, "email": "real@example.com"})

    http_client.post(
        reverse("service:create_ticket"),
        {**FORM, "full_name": "Злой Хакер", "email": "hacker@example.com"},
    )

    client = Client.objects.get()

    assert client.full_name == "Пётр Петров"
    assert client.email == "real@example.com"


@pytest.mark.django_db
def test_typo_in_model_does_not_break_submission(http_client: HttpClient) -> None:
    """Тот же серийник с опечаткой в модели это не повод отдать пятисотку.

    Уникальность в базе стоит на серийном номере, а устройство искалось
    по четырём полям: опечатка давала IntegrityError уже после записи клиента.
    """
    http_client.post(reverse("service:create_ticket"), FORM)

    response = http_client.post(
        reverse("service:create_ticket"), {**FORM, "model": "Lenovo IdeaPadd"}
    )

    assert response.status_code == 302
    assert Ticket.objects.count() == 2
