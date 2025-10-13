from django.urls import path

from . import views


app_name = "mbtispy"

urlpatterns = [
    path("session/", views.create_session, name="create_session"),
    path("session/<str:code>/players/", views.list_players, name="list_players"),
    path(
        "session/<str:code>/register/status/",
        views.registration_status,
        name="registration_status",
    ),
    path(
        "session/<str:code>/role/<int:player_id>/",
        views.get_player_role,
        name="get_player_role",
    ),
    path(
        "session/<str:code>/spy/",
        views.get_spy_mbti,
        name="get_spy_mbti",
    ),
    path(
        "session/<str:code>/register/",
        views.register_player,
        name="register_player",
    ),
    path(
        "session/<str:code>/vote/start/",
        views.start_vote,
        name="start_vote",
    ),
    path("session/<str:code>/vote/", views.vote_endpoint, name="vote"),
    path("session/<str:code>/results/", views.get_results, name="get_results"),
]
