from django.urls import path

from . import views

app_name = "deepfake"

urlpatterns = [
    path("questions/", views.question_feed, name="question-feed"),
    path("selection/", views.selection_challenge, name="selection-challenge"),
]
