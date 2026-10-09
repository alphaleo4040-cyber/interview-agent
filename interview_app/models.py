from django.db import models
from django.contrib.auth.models import User


class InterviewSession(models.Model):
    STATUS_CHOICES = [
        ("in_progress", "In Progress"),
        ("completed", "Completed"),
        ("abandoned", "Abandoned"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="interview_sessions")
    candidate_name = models.CharField(max_length=150, default="Alex")
    target_role = models.CharField(max_length=255, default="Full Stack Software Engineer")
    total_planned_questions = models.PositiveSmallIntegerField(default=4)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="in_progress")
    resume_text = models.TextField(blank=True, default="")
    job_description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.target_role} ({self.status})"


class InterviewQuestionRecord(models.Model):
    session = models.ForeignKey(InterviewSession, on_delete=models.CASCADE, related_name="records")
    question_number = models.PositiveSmallIntegerField()
    topic = models.CharField(max_length=150, default="Technical Assessment")
    question_text = models.TextField(blank=True, default="")
    candidate_answer = models.TextField(blank=True, default="")
    ideal_answer = models.TextField(blank=True, default="")
    score = models.PositiveSmallIntegerField(default=1)  # 1 to 10
    interviewer_notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["question_number"]
        unique_together = ("session", "question_number")

    def __str__(self):
        return f"Q{self.question_number}: {self.topic} ({self.score}/10)"


class InterviewScorecard(models.Model):
    session = models.OneToOneField(InterviewSession, on_delete=models.CASCADE, related_name="scorecard")
    verdict = models.CharField(max_length=50, default="PENDING")
    overall_score = models.PositiveSmallIntegerField(default=0)  # 0 to 100
    competencies = models.JSONField(default=dict)
    key_quote = models.TextField(blank=True, default="")
    strong_moments = models.JSONField(default=list)
    growth_areas = models.JSONField(default=list)
    executive_summary = models.TextField(blank=True, default="")
    full_report_markdown = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Scorecard ({self.session_id}): {self.verdict} - {self.overall_score}/100"


class InterviewChatMessage(models.Model):
    session = models.ForeignKey(InterviewSession, on_delete=models.CASCADE, related_name="chat_messages")
    sender = models.CharField(max_length=20)  # "user" or "agent"
    agent_name = models.CharField(max_length=100, blank=True, default="")
    text = models.TextField()
    is_evaluation = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["session", "created_at"]),
        ]

    def __str__(self):
        return f"[{self.session_id}] {self.sender} ({self.agent_name}): {self.text[:30]}"

