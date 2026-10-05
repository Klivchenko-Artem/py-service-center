"""Формы публичной части: подача заявки и проверка статуса."""

from __future__ import annotations

from django import forms

from service.models import Client, Device, Ticket, default_deadline


class TicketRequestForm(forms.Form):
    """Одна форма на клиента, устройство и заявку.

    Посетителю незачем знать про три сущности: он приносит телевизор и говорит,
    что тот не включается. Раскладывание по таблицам это наша забота.
    """

    full_name = forms.CharField(label="Как вас зовут", max_length=150)
    phone = forms.CharField(label="Телефон", max_length=20)
    email = forms.EmailField(label="Почта", required=False)
    kind = forms.CharField(label="Что за техника", max_length=50)
    model = forms.CharField(label="Модель", max_length=100)
    serial_number = forms.CharField(label="Серийный номер", max_length=64, required=False)
    problem = forms.CharField(label="Что случилось", widget=forms.Textarea(attrs={"rows": 4}))

    def clean_phone(self) -> str:
        """Телефон приводится к одному виду: по нему ищется клиент."""
        digits = "".join(ch for ch in self.cleaned_data["phone"] if ch.isdigit())

        if len(digits) < 10:
            raise forms.ValidationError("Телефон похож на неполный")

        if len(digits) == 11 and digits[0] == "8":
            digits = "7" + digits[1:]

        return "+" + digits

    def save(self) -> Ticket:
        data = self.cleaned_data

        client, created = Client.objects.get_or_create(
            phone=data["phone"],
            defaults={"full_name": data["full_name"], "email": data["email"]},
        )

        # Карточку постоянного клиента отсюда не правим.
        #
        # Форма анонимная, и знания чужого телефона хватало, чтобы переписать
        # человеку имя и почту. Пустые поля дозаполнить можно это не подмена,
        # а всё остальное разбирает приёмщик в админке.
        if not created:
            filled = []

            if not client.full_name and data["full_name"]:
                client.full_name = data["full_name"]
                filled.append("full_name")

            if not client.email and data["email"]:
                client.email = data["email"]
                filled.append("email")

            if filled:
                client.save(update_fields=filled)

        device = self._find_or_create_device(client, data)

        return Ticket.objects.create(
            client=client,
            device=device,
            problem=data["problem"],
            deadline=default_deadline(),
        )


    @staticmethod
    def _find_or_create_device(client, data):
        """Находит аппарат клиента или заводит новый.

        Искать по четырём полям нельзя: уникальность в базе стоит только
        на непустом серийнике, и опечатка в модели («Ipnone 12») давала
        IntegrityError и пятисотку, при уже записанном клиенте.
        """
        serial = data["serial_number"]

        if serial:
            device = Device.objects.filter(serial_number=serial).first()

            if device is not None:
                return device

            return Device.objects.create(
                client=client,
                kind=data["kind"],
                model=data["model"],
                serial_number=serial,
            )

        # Без серийника аппараты различаем по виду и модели: пустых серийников
        # в базе может быть сколько угодно
        device, _ = Device.objects.get_or_create(
            client=client,
            kind=data["kind"],
            model=data["model"],
            serial_number="",
        )

        return device


class TicketStatusForm(forms.Form):
    """Проверка статуса: номер заявки плюс телефон.

    Одного номера мало: они идут подряд, и по ним можно было бы листать чужие
    заявки.
    """

    number = forms.CharField(label="Номер заявки", max_length=12)
    phone = forms.CharField(label="Телефон", max_length=20)

    def find(self) -> Ticket | None:
        digits = "".join(ch for ch in self.cleaned_data["phone"] if ch.isdigit())

        if len(digits) == 11 and digits[0] == "8":
            digits = "7" + digits[1:]

        return (
            Ticket.objects.select_related("client", "device")
            .filter(number=self.cleaned_data["number"].strip(), client__phone="+" + digits)
            .first()
        )
