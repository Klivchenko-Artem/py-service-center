"""Маршруты публичной части."""

from django.urls import path

from service import views

app_name = "service"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("new/", views.create_ticket, name="create_ticket"),
    path("new/<str:number>/", views.ticket_created, name="ticket_created"),
    path("status/", views.ticket_status, name="ticket_status"),
]
