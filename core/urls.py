from django.urls import path

from . import views

urlpatterns = [
    path("", views.front_page, name="home"),
    path("new/", views.new_page, name="new"),
    path("submit/", views.submit, name="submit"),
    path("api/extract-metadata/", views.api_extract_metadata, name="api_extract_metadata"),
    path("item/<int:pk>/", views.submission_detail, name="submission_detail"),
    path("item/<int:sub_pk>/reply/<int:comment_pk>/", views.reply, name="reply"),
    path("vote/submission/<int:pk>/", views.vote_submission, name="vote_submission"),
    path("vote/comment/<int:pk>/", views.vote_comment, name="vote_comment"),
    path("save/submission/<int:pk>/", views.toggle_save, name="toggle_save"),
    path("saved/", views.saved_page, name="saved"),
    path("u/<str:username>/", views.user_page, name="user_page"),
    path("signup/", views.signup, name="signup"),
    path("communities/", views.communities_index, name="communities"),
    path("c/<slug:slug>/", views.community_detail, name="community_detail"),
    path("c/<slug:slug>/join/", views.join_community, name="join_community"),
    path("c/<slug:slug>/leave/", views.leave_community, name="leave_community"),
]
