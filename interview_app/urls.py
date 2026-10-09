from django.urls import path
from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("register/", views.register_view, name="register"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("api/upload-resume/", views.upload_resume, name="upload_resume"),
    path("api/job-descriptions/", views.get_job_descriptions, name="get_job_descriptions"),
    path("api/start/", views.start_interview, name="start_interview"),
    path("api/chat/", views.chat_message, name="chat_message"),
    path("api/finish/", views.finish_interview, name="finish_interview"),
    path("api/status/", views.get_status, name="get_status"),
    path("api/history/", views.list_interview_history, name="list_interview_history"),
    path("api/history/<int:session_id>/", views.get_interview_history_detail, name="get_interview_history_detail"),
    path("api/history/<int:session_id>/switch/", views.switch_interview_session, name="switch_interview_session"),
    path("api/history/<int:session_id>/delete/", views.delete_interview_session, name="delete_interview_session"),
]


