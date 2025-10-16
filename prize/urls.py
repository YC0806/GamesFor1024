from django.urls import path

from . import views


app_name = "prize"

urlpatterns = [
    path("draw/", views.get_prize, name="get_prize"),
    path("list/", views.list_prizes, name="list_prizes"),
]
