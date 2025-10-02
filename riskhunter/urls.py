from django.urls import path

from . import views

app_name = "riskhunter"

urlpatterns = [
    path("scenarios/", views.scenario_feed, name="scenario_feed"),
]
