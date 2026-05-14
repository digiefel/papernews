from django.urls import path

from . import views

urlpatterns = [
    path("", views.front_page, name="home"),
    path("new/", views.new_page, name="new"),
    path("submit/", views.submit, name="submit"),
    path("item/<int:pk>/", views.submission_detail, name="submission_detail"),
    path("vote/submission/<int:pk>/", views.vote_submission, name="vote_submission"),
    path("vote/comment/<int:pk>/", views.vote_comment, name="vote_comment"),
    path("signup/", views.signup, name="signup"),
]
