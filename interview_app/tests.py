import json
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse


class InterviewAppTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="testcandidate",
            email="candidate@example.com",
            password="SecurePassword123!",
            first_name="Jane",
            last_name="Doe",
        )

    def test_login_and_access_index(self):
        login_success = self.client.login(username="testcandidate", password="SecurePassword123!")
        self.assertTrue(login_success)

        response = self.client.get(reverse("index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Jane Doe")

    def test_unauthenticated_redirect_to_login(self):
        response = self.client.get(reverse("index"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_get_job_descriptions_api(self):
        self.client.login(username="testcandidate", password="SecurePassword123!")
        response = self.client.get(reverse("get_job_descriptions"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("success"))
        self.assertIn("Full Stack Software Engineer", data.get("templates", {}))

    def test_upload_resume_txt(self):
        self.client.login(username="testcandidate", password="SecurePassword123!")
        sample_file = SimpleUploadedFile(
            "resume.txt",
            b"Experienced Full Stack Engineer skilled in Python, Django, React, and AWS.",
            content_type="text/plain",
        )
        response = self.client.post(
            reverse("upload_resume"),
            {"resume_file": sample_file},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data.get("success"))
        self.assertIn("Python, Django, React", data.get("extracted_text"))

    def test_zero_question_scorecard_and_finish(self):
        from interview_app.tools import InterviewState
        from interview_app.views import _get_effective_scorecard

        state = InterviewState(candidate_name="Jane", target_role="Software Engineer", total_planned_questions=4)
        scorecard = _get_effective_scorecard(state)
        self.assertEqual(scorecard["overall_score"], 0)
        self.assertEqual(scorecard["verdict"], "NO HIRE")
        self.assertEqual(scorecard["competencies"]["technical_mastery"], 0)

    def test_partial_interview_completion_adjusted_scorecard(self):
        from interview_app.tools import InterviewState
        from interview_app.views import _get_effective_scorecard

        state = InterviewState(candidate_name="Jane", target_role="Software Engineer", total_planned_questions=4)
        # 1 of 4 answered with 8/10 -> prorated score = 8 / 40 * 100 = 20/100
        state.add_record(1, "Python Basics", "Answered well", 8, "Good")
        scorecard = _get_effective_scorecard(state)
        self.assertEqual(scorecard["overall_score"], 20)
        self.assertEqual(scorecard["verdict"], "NO HIRE")

    def test_database_persistence_lifecycle(self):
        from interview_app.models import InterviewSession, InterviewQuestionRecord, InterviewScorecard
        from interview_app.tools import InterviewState
        from interview_app.views import _persist_scorecard_and_completion

        # 1. Create DB session
        db_session = InterviewSession.objects.create(
            user=self.user,
            target_role="Backend Developer",
            total_planned_questions=3,
            status="in_progress",
        )
        self.assertEqual(db_session.status, "in_progress")

        # 2. Add question turns via state
        state = InterviewState(
            candidate_name="Jane",
            target_role="Backend Developer",
            total_planned_questions=3,
            db_session_id=db_session.id,
        )
        state.add_record(1, "Django ORM", "Explained select_related", 9, "Strong understanding")
        state.add_record(2, "PostgreSQL", "Discussed B-tree indexing", 8, "Solid")

        # Verify InterviewQuestionRecords were written to DB
        q_records = InterviewQuestionRecord.objects.filter(session=db_session).order_by("question_number")
        self.assertEqual(q_records.count(), 2)
        self.assertEqual(q_records[0].question_number, 1)
        self.assertEqual(q_records[0].score, 9)
        self.assertEqual(q_records[1].question_number, 2)
        self.assertEqual(q_records[1].score, 8)

        # 3. Complete and persist scorecard
        sample_scorecard = {
            "verdict": "STRONG HIRE",
            "overall_score": 85,
            "competencies": {"technical_mastery": 85, "system_architecture": 80, "problem_solving": 90, "communication": 85},
            "key_quote": "Always optimize querysets with select_related",
            "strong_moments": ["ORM mastery", "Database indexing"],
            "growth_areas": ["Caching layers"],
            "executive_summary": "Top candidate.",
        }
        _persist_scorecard_and_completion(db_session.id, sample_scorecard, "# Report Markdown")

        db_session.refresh_from_db()
        self.assertEqual(db_session.status, "completed")
        self.assertTrue(hasattr(db_session, "scorecard"))
        self.assertEqual(db_session.scorecard.verdict, "STRONG HIRE")
        self.assertEqual(db_session.scorecard.overall_score, 85)
        self.assertEqual(db_session.scorecard.full_report_markdown, "# Report Markdown")

    def test_get_status_recovers_active_db_session(self):
        from interview_app.models import InterviewSession, InterviewQuestionRecord
        from interview_app.views import interview_sessions, session_states

        # Clear in-memory caches to simulate server restart / worker cold start
        interview_sessions.clear()
        session_states.clear()

        # Create active in-progress session in DB
        db_session = InterviewSession.objects.create(
            user=self.user,
            target_role="DevOps Engineer",
            total_planned_questions=4,
            status="in_progress",
        )
        InterviewQuestionRecord.objects.create(
            session=db_session,
            question_number=1,
            topic="Docker & Kubernetes",
            candidate_answer="Explained pod lifecycle",
            score=9,
            interviewer_notes="Excellent container knowledge",
        )

        self.client.login(username="testcandidate", password="SecurePassword123!")
        response = self.client.get(reverse("get_status"))
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertTrue(data.get("has_active_session"))
        self.assertEqual(data.get("target_role"), "DevOps Engineer")
        self.assertEqual(len(data.get("records", [])), 1)
        self.assertEqual(data["records"][0]["question_number"], 1)
        self.assertEqual(data["records"][0]["score"], 9)

    def test_history_list_and_delete(self):
        from interview_app.models import InterviewSession
        session = InterviewSession.objects.create(
            user=self.user,
            target_role="Frontend Engineer",
            total_planned_questions=2,
            status="completed",
        )
        self.client.login(username="testcandidate", password="SecurePassword123!")
        
        # List history
        res_list = self.client.get(reverse("list_interview_history"))
        self.assertEqual(res_list.status_code, 200)
        data_list = res_list.json()
        self.assertTrue(data_list["success"])
        self.assertTrue(any(s["id"] == session.id for s in data_list["sessions"]))

        # Detail history
        res_detail = self.client.get(reverse("get_interview_history_detail", args=[session.id]))
        self.assertEqual(res_detail.status_code, 200)
        data_detail = res_detail.json()
        self.assertTrue(data_detail["success"])

        # Delete history via DELETE HTTP method
        res_del = self.client.delete(reverse("get_interview_history_detail", args=[session.id]))
        self.assertEqual(res_del.status_code, 200)
        self.assertTrue(res_del.json()["success"])
        self.assertFalse(InterviewSession.objects.filter(id=session.id).exists())

    def test_history_switch_session(self):
        from interview_app.models import InterviewSession, InterviewQuestionRecord
        session = InterviewSession.objects.create(
            user=self.user,
            target_role="AI Engineer",
            total_planned_questions=3,
            status="completed",
        )
        InterviewQuestionRecord.objects.create(
            session=session,
            question_number=1,
            topic="PyTorch",
            candidate_answer="Trained transformers",
            score=9,
            interviewer_notes="Strong deep learning background",
        )
        self.client.login(username="testcandidate", password="SecurePassword123!")
        res_switch = self.client.post(reverse("switch_interview_session", args=[session.id]))
        self.assertEqual(res_switch.status_code, 200)
        data_switch = res_switch.json()
        self.assertTrue(data_switch["success"])
        self.assertEqual(data_switch["target_role"], "AI Engineer")
        self.assertEqual(len(data_switch["records"]), 1)
        self.assertEqual(data_switch["records"][0]["topic"], "PyTorch")



