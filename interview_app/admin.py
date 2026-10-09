import csv
from django.contrib import admin
from django.http import HttpResponse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import (
    InterviewSession,
    InterviewQuestionRecord,
    InterviewScorecard,
    InterviewChatMessage,
)


# ==========================================
# Inlines
# ==========================================

class InterviewScorecardInline(admin.StackedInline):
    model = InterviewScorecard
    can_delete = False
    extra = 0
    fields = (
        "verdict",
        "overall_score",
        "formatted_competencies",
        "formatted_strong_moments",
        "formatted_growth_areas",
        "key_quote",
        "executive_summary",
        "full_report_markdown",
    )
    readonly_fields = (
        "formatted_competencies",
        "formatted_strong_moments",
        "formatted_growth_areas",
    )

    @admin.display(description="Competencies")
    def formatted_competencies(self, obj):
        if not obj or not obj.competencies:
            return "-"
        items = [f"<li><b>{k}:</b> {v}</li>" for k, v in obj.competencies.items()]
        return format_html("<ul>{}</ul>", mark_safe("".join(items)))

    @admin.display(description="Strong Moments")
    def formatted_strong_moments(self, obj):
        if not obj or not obj.strong_moments:
            return "-"
        items = [f"<li>{item}</li>" for item in obj.strong_moments]
        return format_html("<ul>{}</ul>", mark_safe("".join(items)))

    @admin.display(description="Growth Areas")
    def formatted_growth_areas(self, obj):
        if not obj or not obj.growth_areas:
            return "-"
        items = [f"<li>{item}</li>" for item in obj.growth_areas]
        return format_html("<ul>{}</ul>", mark_safe("".join(items)))


class InterviewQuestionRecordInline(admin.TabularInline):
    model = InterviewQuestionRecord
    extra = 0
    fields = ("question_number", "topic", "score", "question_text", "candidate_answer", "interviewer_notes")
    show_change_link = True


class InterviewChatMessageInline(admin.TabularInline):
    model = InterviewChatMessage
    extra = 0
    fields = ("sender", "agent_name", "text", "is_evaluation", "created_at")
    readonly_fields = ("created_at",)
    classes = ("collapse",)
    show_change_link = True


# ==========================================
# Actions
# ==========================================

@admin.action(description="Export selected sessions to CSV")
def export_sessions_as_csv(modeladmin, request, queryset):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="interview_sessions.csv"'
    writer = csv.writer(response)
    writer.writerow([
        "ID",
        "Candidate Name",
        "User",
        "Target Role",
        "Status",
        "Total Questions",
        "Score",
        "Verdict",
        "Created At",
    ])
    for s in queryset.select_related("user").prefetch_related("scorecard"):
        score = s.scorecard.overall_score if hasattr(s, "scorecard") and s.scorecard else "N/A"
        verdict = s.scorecard.verdict if hasattr(s, "scorecard") and s.scorecard else "N/A"
        writer.writerow([
            s.id,
            s.candidate_name,
            s.user.username if s.user else "",
            s.target_role,
            s.status,
            s.total_planned_questions,
            score,
            verdict,
            s.created_at.strftime("%Y-%m-%d %H:%M"),
        ])
    return response


@admin.action(description="Mark selected as Completed")
def mark_as_completed(modeladmin, request, queryset):
    updated = queryset.update(status="completed")
    modeladmin.message_user(request, f"{updated} session(s) marked as completed.")


@admin.action(description="Mark selected as Abandoned")
def mark_as_abandoned(modeladmin, request, queryset):
    updated = queryset.update(status="abandoned")
    modeladmin.message_user(request, f"{updated} session(s) marked as abandoned.")


# ==========================================
# Model Admins (Standard Django Framework)
# ==========================================

@admin.register(InterviewSession)
class InterviewSessionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "candidate_name",
        "user",
        "target_role",
        "status_badge",
        "score_badge",
        "total_planned_questions",
        "created_at",
    )
    list_filter = ("status", "created_at")
    search_fields = ("candidate_name", "user__username", "user__email", "target_role")
    readonly_fields = ("created_at", "updated_at", "score_badge")
    inlines = [InterviewScorecardInline, InterviewQuestionRecordInline, InterviewChatMessageInline]
    actions = [export_sessions_as_csv, mark_as_completed, mark_as_abandoned]

    fieldsets = (
        ("Session Overview", {
            "fields": ("user", "candidate_name", "target_role", "status", "total_planned_questions", "score_badge")
        }),
        ("Resume & Job Details", {
            "classes": ("collapse",),
            "fields": ("resume_text", "job_description")
        }),
        ("Timestamps", {
            "fields": ("created_at", "updated_at")
        }),
    )

    @admin.display(description="Status")
    def status_badge(self, obj):
        colors = {
            "completed": ("#16a34a", "#dcfce7"),
            "in_progress": ("#2563eb", "#dbeafe"),
            "abandoned": ("#dc2626", "#fee2e2"),
        }
        text_color, bg_color = colors.get(obj.status, ("#4b5563", "#f3f4f6"))
        label = obj.get_status_display()
        return format_html(
            '<span style="background-color: {}; color: {}; padding: 3px 8px; border-radius: 9999px; font-weight: 600; font-size: 11px; text-transform: uppercase;">{}</span>',
            bg_color,
            text_color,
            label,
        )

    @admin.display(description="Score / Verdict")
    def score_badge(self, obj):
        if hasattr(obj, "scorecard") and obj.scorecard:
            score = obj.scorecard.overall_score
            verdict = obj.scorecard.verdict
            if score >= 75:
                bg, text = "#dcfce7", "#16a34a"
            elif score >= 50:
                bg, text = "#fef9c3", "#ca8a04"
            else:
                bg, text = "#fee2e2", "#dc2626"
            return format_html(
                '<span style="background-color: {}; color: {}; padding: 3px 8px; border-radius: 6px; font-weight: 600; font-size: 11px;">{} ({} / 100)</span>',
                bg,
                text,
                verdict,
                score,
            )
        return format_html('<span style="color: #9ca3af; font-size: 11px;">No scorecard</span>')


@admin.register(InterviewScorecard)
class InterviewScorecardAdmin(admin.ModelAdmin):
    list_display = ("id", "session_candidate", "verdict_badge", "overall_score", "created_at")
    list_filter = ("verdict", "created_at")
    search_fields = ("session__candidate_name", "session__user__username", "verdict", "executive_summary")
    readonly_fields = ("created_at", "formatted_competencies", "formatted_strong_moments", "formatted_growth_areas")

    fields = (
        "session",
        "verdict",
        "overall_score",
        "formatted_competencies",
        "formatted_strong_moments",
        "formatted_growth_areas",
        "key_quote",
        "executive_summary",
        "full_report_markdown",
        "created_at",
    )

    @admin.display(description="Candidate")
    def session_candidate(self, obj):
        return obj.session.candidate_name

    @admin.display(description="Verdict")
    def verdict_badge(self, obj):
        score = obj.overall_score
        if score >= 75:
            bg, text = "#dcfce7", "#16a34a"
        elif score >= 50:
            bg, text = "#fef9c3", "#ca8a04"
        else:
            bg, text = "#fee2e2", "#dc2626"
        return format_html(
            '<span style="background-color: {}; color: {}; padding: 3px 8px; border-radius: 6px; font-weight: 600; font-size: 11px;">{}</span>',
            bg,
            text,
            obj.verdict,
        )

    @admin.display(description="Competencies")
    def formatted_competencies(self, obj):
        if not obj.competencies:
            return "-"
        items = [f"<li><b>{k}:</b> {v}</li>" for k, v in obj.competencies.items()]
        return format_html("<ul>{}</ul>", mark_safe("".join(items)))

    @admin.display(description="Strong Moments")
    def formatted_strong_moments(self, obj):
        if not obj.strong_moments:
            return "-"
        items = [f"<li>{item}</li>" for item in obj.strong_moments]
        return format_html("<ul>{}</ul>", mark_safe("".join(items)))

    @admin.display(description="Growth Areas")
    def formatted_growth_areas(self, obj):
        if not obj.growth_areas:
            return "-"
        items = [f"<li>{item}</li>" for item in obj.growth_areas]
        return format_html("<ul>{}</ul>", mark_safe("".join(items)))


@admin.register(InterviewQuestionRecord)
class InterviewQuestionRecordAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "session_candidate",
        "question_number",
        "topic",
        "score_badge",
        "short_question",
        "created_at",
    )
    list_filter = ("topic", "score", "created_at")
    search_fields = ("session__candidate_name", "topic", "question_text", "candidate_answer")
    readonly_fields = ("created_at",)

    @admin.display(description="Candidate")
    def session_candidate(self, obj):
        return obj.session.candidate_name

    @admin.display(description="Score")
    def score_badge(self, obj):
        if obj.score >= 7:
            bg, text = "#dcfce7", "#16a34a"
        elif obj.score >= 4:
            bg, text = "#fef9c3", "#ca8a04"
        else:
            bg, text = "#fee2e2", "#dc2626"
        return format_html(
            '<span style="background-color: {}; color: {}; padding: 2px 6px; border-radius: 4px; font-weight: 600; font-size: 11px;">{}/10</span>',
            bg,
            text,
            obj.score,
        )

    @admin.display(description="Question")
    def short_question(self, obj):
        return (obj.question_text[:60] + "...") if len(obj.question_text) > 60 else obj.question_text


@admin.register(InterviewChatMessage)
class InterviewChatMessageAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "session_candidate",
        "sender_badge",
        "agent_name",
        "short_text",
        "is_evaluation",
        "created_at",
    )
    list_filter = ("sender", "is_evaluation", "created_at")
    search_fields = ("session__candidate_name", "text", "agent_name")
    readonly_fields = ("created_at",)

    @admin.display(description="Candidate")
    def session_candidate(self, obj):
        return obj.session.candidate_name

    @admin.display(description="Sender")
    def sender_badge(self, obj):
        if obj.sender == "agent":
            bg, text = "#e0e7ff", "#4338ca"
        else:
            bg, text = "#f3f4f6", "#1f2937"
        return format_html(
            '<span style="background-color: {}; color: {}; padding: 2px 6px; border-radius: 4px; font-weight: 600; font-size: 11px;">{}</span>',
            bg,
            text,
            obj.sender.upper(),
        )

    @admin.display(description="Message")
    def short_text(self, obj):
        return (obj.text[:80] + "...") if len(obj.text) > 80 else obj.text
