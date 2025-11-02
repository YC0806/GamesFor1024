from django.urls import path

from . import views

app_name = "mbtitest"

urlpatterns = [
    path("questions/", views.llm_questions, name="questions"),
    path("evaluate/", views.evaluate_answers, name="evaluate"),
]
