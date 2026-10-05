"""Публичная часть: подать заявку и узнать её статус."""

from __future__ import annotations

from django.db.models import Avg, Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from service.forms import TicketRequestForm, TicketStatusForm
from service.models import Ticket


@require_http_methods(["GET", "POST"])
def create_ticket(request):
    """Приём заявки без регистрации: человек оставляет технику и получает номер."""
    if request.method == "POST":
        form = TicketRequestForm(request.POST)

        if form.is_valid():
            ticket = form.save()
            _remember_ticket(request, ticket.number)

            # Редирект после успешной отправки: иначе обновление страницы
            # заведёт вторую такую же заявку
            return redirect("service:ticket_created", number=ticket.number)
    else:
        form = TicketRequestForm()

    return render(request, "service/create.html", {"form": form})


#: Сколько номеров помним в сессии: человек может сдать несколько аппаратов
#: за один заход, но и держать бесконечный список в куке незачем.
REMEMBERED_TICKETS = 20

SESSION_KEY = "created_tickets"


def _remember_ticket(request, number: str) -> None:
    """Запоминает в сессии, что эту заявку подали с этого устройства."""
    numbers = request.session.get(SESSION_KEY, [])
    numbers.append(number)
    request.session[SESSION_KEY] = numbers[-REMEMBERED_TICKETS:]


def ticket_created(request, number: str):
    """Страница «заявка принята».

    Показывается только тому, кто заявку и подал: номера идут подряд
    (26-0001, 26-0002...), и без этой проверки вся база ремонтов вместе
    с телефонами выкачивалась циклом curl. Всем остальным, форма проверки
    статуса, где кроме номера спрашивают телефон.
    """
    if number not in request.session.get(SESSION_KEY, []):
        raise Http404("Заявка не найдена")

    ticket = get_object_or_404(Ticket, number=number)

    return render(request, "service/created.html", {"ticket": ticket})


@require_http_methods(["GET", "POST"])
def ticket_status(request):
    """Статус по номеру и телефону."""
    ticket = None
    not_found = False

    if request.method == "POST":
        form = TicketStatusForm(request.POST)

        if form.is_valid():
            ticket = form.find()
            not_found = ticket is None
    else:
        form = TicketStatusForm()

    return render(
        request,
        "service/status.html",
        {"form": form, "ticket": ticket, "not_found": not_found},
    )


def dashboard(request):
    """Витрина: сколько заявок в работе и как быстро их закрывают."""
    stats = Ticket.objects.aggregate(
        total=Count("id"),
        open=Count("id", filter=~Q(status__in=[Ticket.Status.DONE, Ticket.Status.REJECTED])),
        done=Count("id", filter=Q(status=Ticket.Status.DONE)),
        avg_price=Avg("price", filter=Q(status=Ticket.Status.DONE)),
    )

    by_status = (
        Ticket.objects.values("status").annotate(count=Count("id")).order_by("-count")
    )

    labels = dict(Ticket.Status.choices)

    return render(
        request,
        "service/dashboard.html",
        {
            "stats": stats,
            # get, а не квадратные скобки: статус, оставшийся в базе от старой
            # версии choices, уронил бы публичную витрину KeyError-ом
            "by_status": [
                {"label": labels.get(row["status"], row["status"]), "count": row["count"]}
                for row in by_status
            ],
        },
    )
