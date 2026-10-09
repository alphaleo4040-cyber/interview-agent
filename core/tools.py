from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import logging
from contextvars import ContextVar
from agents import function_tool

logger = logging.getLogger(__name__)


@dataclass
class QuestionRecord:
    question_number: int
    topic: str = ""
    candidate_answer_summary: str = ""
    score: int = 1  # 1 to 10
    notes: str = ""
    question_text: str = ""
    ideal_answer: str = ""


@dataclass
class InterviewState:
    candidate_name: str = "Candidate"
    target_role: str = "Software Engineer"
    total_planned_questions: int = 5
    resume_text: str = ""
    job_description: str = ""
    db_session_id: Optional[int] = None
    records: List[QuestionRecord] = field(default_factory=list)
    scorecard: Dict[str, Any] = field(default_factory=dict)

    def add_record(
        self,
        question_number: int,
        topic: str = "",
        candidate_answer_summary: str = "",
        score: int = 1,
        notes: str = "",
        question_text: str = "",
        ideal_answer: str = "",
    ) -> None:
        clean_score = max(1, min(10, score))
        clean_topic = topic or f"Question {question_number}"
        self.scorecard = {}

        for r in self.records:
            if r.question_number == question_number:
                r.topic = clean_topic
                r.candidate_answer_summary = candidate_answer_summary or r.candidate_answer_summary
                r.score = clean_score
                r.notes = notes or r.notes
                if question_text:
                    r.question_text = question_text
                if ideal_answer:
                    r.ideal_answer = ideal_answer
                self._persist_record_to_db(r)
                return

        record = QuestionRecord(
            question_number=question_number,
            topic=clean_topic,
            candidate_answer_summary=candidate_answer_summary,
            score=clean_score,
            notes=notes,
            question_text=question_text,
            ideal_answer=ideal_answer,
        )
        self.records.append(record)
        self._persist_record_to_db(record)

    def _persist_record_to_db(self, record: QuestionRecord) -> None:
        if not self.db_session_id:
            return
        try:
            from interview_app.models import InterviewQuestionRecord
            InterviewQuestionRecord.objects.update_or_create(
                session_id=self.db_session_id,
                question_number=record.question_number,
                defaults={
                    "topic": record.topic,
                    "question_text": record.question_text,
                    "candidate_answer": record.candidate_answer_summary,
                    "ideal_answer": record.ideal_answer,
                    "score": record.score,
                    "interviewer_notes": record.notes,
                },
            )
        except Exception as e:
            logger.debug(f"Could not persist question record to DB: {e}")

    def summary(self) -> str:
        total = max(1, self.total_planned_questions)
        completed = len(self.records)

        if not self.records:
            return (
                f"Candidate: {self.candidate_name}\n"
                f"Target Role: {self.target_role}\n"
                f"Planned Questions: {total}\n"
                f"Questions Completed: 0 of {total} (INCOMPLETE - Session ended before any questions were answered)\n"
                f"Overall Score: 0/100 (NO HIRE)\n"
                "No questions evaluated yet."
            )

        avg_score = sum(r.score for r in self.records) / completed
        prorated_score = max(0, min(100, int((sum(r.score for r in self.records) / (total * 10)) * 100)))
        status_note = "COMPLETED" if completed >= total else f"INCOMPLETE ({completed} of {total} answered)"

        lines = [
            f"Candidate: {self.candidate_name}",
            f"Target Role: {self.target_role}",
            f"Interview Status: {status_note}",
            f"Questions Completed: {completed} of {total}",
            f"Average Score on Answered Questions: {avg_score:.1f}/10",
            f"Completion-Adjusted Score: {prorated_score}/100",
            "\nEvaluated Responses:",
        ]
        for r in self.records:
            ans_part = f" | Answer Summary: {r.candidate_answer_summary}" if r.candidate_answer_summary else ""
            lines.append(
                f"- Q{r.question_number} [{r.topic}]: Score {r.score}/10{ans_part} | Notes: {r.notes}"
            )
        return "\n".join(lines)


# Context variable for thread-safe active session ID
active_session_id: ContextVar[str] = ContextVar("active_session_id", default="default")
session_states: Dict[str, InterviewState] = {}


def get_current_interview_state() -> InterviewState:
    """Retrieve InterviewState for active session."""
    sid = active_session_id.get()
    if sid not in session_states:
        session_states[sid] = InterviewState()
    return session_states[sid]


# Default interview state alias for CLI backward compatibility
interview_state = get_current_interview_state()


@function_tool
def record_question_feedback(
    question_number: int,
    topic: str = "Technical Assessment",
    candidate_answer_summary: str = "Candidate provided response.",
    score: int = 7,
    notes: str = "Answer evaluated.",
    question_text: str = "",
) -> str:
    """Record scoring and feedback for a candidate's answer to an interview question.

    Args:
        question_number: The sequential number of the question (e.g. 1, 2, 3).
        topic: The topic or category (e.g., 'System Design', 'Python Fundamentals', 'Behavioral - Conflict Resolution').
        candidate_answer_summary: Brief summary of the candidate's answer or 'Question skipped by candidate.'
        score: Rating from 1 (poor) to 10 (exceptional).
        notes: Constructive notes on strengths or deficiencies.
        question_text: The full text of the interview question that was asked.
    """
    state = get_current_interview_state()
    state.add_record(
        question_number=question_number,
        topic=topic,
        candidate_answer_summary=candidate_answer_summary,
        score=score,
        notes=notes,
        question_text=question_text,
    )
    return (
        f"Successfully recorded score {score}/10 for Question {question_number} ({topic}). "
        f"Total questions recorded: {len(state.records)}."
    )


@function_tool
def get_interview_progress(include_details: bool = True) -> str:
    """Get current progress and evaluation summary of the interview.

    Args:
        include_details: Whether to return detailed performance breakdown (default True).
    """
    state = get_current_interview_state()
    return state.summary()


@function_tool
def record_evaluation_scorecard(
    verdict: str = "NO HIRE",
    overall_score: int = 0,
    technical_mastery_score: int = 0,
    system_architecture_score: int = 0,
    problem_solving_score: int = 0,
    communication_score: int = 0,
    key_candidate_quote: str = "",
    strong_moments: str = "",
    growth_areas: str = "",
    executive_summary: str = "",
) -> str:
    """Record a structured Vettora evaluation scorecard.

    Args:
        verdict: Recommendation ('STRONG HIRE', 'HIRE', 'MAYBE', 'NO HIRE').
        overall_score: Total rating from 0 to 100.
        technical_mastery_score: Rating 0-100 on technical concepts and coding.
        system_architecture_score: Rating 0-100 on system architecture and design.
        problem_solving_score: Rating 0-100 on analytical problem solving.
        communication_score: Rating 0-100 on communication clarity and structure.
        key_candidate_quote: Direct technical quote from the candidate.
        strong_moments: Semicolon-separated list of 2-3 key strengths.
        growth_areas: Semicolon-separated list of 2-3 development areas.
        executive_summary: Executive summary of hiring recommendation.
    """
    state = get_current_interview_state()

    def _split_items(text: str) -> List[str]:
        if not text:
            return []
        items = [s.strip(" -•*") for s in text.replace("\n", ";").split(";") if s.strip(" -•*")]
        return items or [text.strip()]

    state.scorecard = {
        "verdict": verdict.strip().upper(),
        "overall_score": max(0, min(100, int(overall_score))),
        "competencies": {
            "technical_mastery": max(0, min(100, int(technical_mastery_score))),
            "system_architecture": max(0, min(100, int(system_architecture_score))),
            "problem_solving": max(0, min(100, int(problem_solving_score))),
            "communication": max(0, min(100, int(communication_score))),
        },
        "key_quote": key_candidate_quote.strip(),
        "strong_moments": _split_items(strong_moments),
        "growth_areas": _split_items(growth_areas),
        "executive_summary": executive_summary.strip(),
    }

    if state.db_session_id:
        try:
            from interview_app.models import InterviewScorecard, InterviewSession
            InterviewScorecard.objects.update_or_create(
                session_id=state.db_session_id,
                defaults={
                    "verdict": state.scorecard["verdict"],
                    "overall_score": state.scorecard["overall_score"],
                    "competencies": state.scorecard["competencies"],
                    "key_quote": state.scorecard["key_quote"],
                    "strong_moments": state.scorecard["strong_moments"],
                    "growth_areas": state.scorecard["growth_areas"],
                    "executive_summary": state.scorecard["executive_summary"],
                },
            )
            InterviewSession.objects.filter(id=state.db_session_id).update(status="completed")
        except Exception as e:
            logger.debug(f"Could not persist scorecard to DB: {e}")

    return (
        f"Successfully recorded Vettora Scorecard: Verdict={verdict}, "
        f"Overall Score={overall_score}/100."
    )
