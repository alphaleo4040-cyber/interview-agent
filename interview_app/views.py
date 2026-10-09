import json
import logging
from typing import Dict, Any

from django.contrib.auth import login as auth_login, logout as auth_logout, authenticate
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpRequest, HttpResponse
from django.shortcuts import render, redirect
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST, require_GET

from agents import Runner
from openai import OpenAI
from .config import (
    create_groq_model,
    get_groq_model_name,
    get_groq_api_key,
    GROQ_BASE_URL,
)
from .session import InMemorySession
from .tools import active_session_id, session_states, InterviewState, QuestionRecord
from .interview_agents import create_evaluator_agent, create_interviewer_agent
from .resume_parser import parse_resume_file, POPULAR_JOB_DESCRIPTIONS
from .forms import RegistrationForm, LoginForm
from .models import (
    InterviewSession,
    InterviewQuestionRecord,
    InterviewScorecard,
    InterviewChatMessage,
)

logger = logging.getLogger(__name__)


def _serialize_record(r: Any) -> Dict[str, Any]:
    """Uniformly serialize QuestionRecord dataclass or Django model."""
    candidate_ans = getattr(r, "candidate_answer_summary", "") or getattr(r, "candidate_answer", "")
    notes = getattr(r, "notes", "") or getattr(r, "interviewer_notes", "")
    return {
        "question_number": r.question_number,
        "topic": r.topic,
        "question_text": getattr(r, "question_text", ""),
        "candidate_answer": candidate_ans,
        "ideal_answer": getattr(r, "ideal_answer", ""),
        "score": r.score,
        "notes": notes,
    }

# In-memory store for active web sessions
# Key: Django session_key -> Value: Dict containing agents, session, state, messages
interview_sessions: Dict[str, Dict[str, Any]] = {}


def _get_or_create_session_key(request: HttpRequest) -> str:
    """Ensure Django session exists and return session key."""
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


def register_view(request: HttpRequest) -> HttpResponse:
    """Register a new user account and log in."""
    if request.user.is_authenticated:
        return redirect("index")

    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_login(request, user)
            return redirect("index")
    else:
        form = RegistrationForm()

    return render(request, "register.html", {"form": form})


def login_view(request: HttpRequest) -> HttpResponse:
    """Authenticate and log in an existing user."""
    if request.user.is_authenticated:
        return redirect("index")

    if request.method == "POST":
        form = LoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data["username"]
            password = form.cleaned_data["password"]
            user = authenticate(request, username=username, password=password)
            if user is not None:
                auth_login(request, user)
                next_url = request.GET.get("next", "index")
                return redirect(next_url)
            else:
                form.add_error(None, "Invalid username or password.")
    else:
        form = LoginForm()

    return render(request, "login.html", {"form": form})


def logout_view(request: HttpRequest) -> HttpResponse:
    """Log out the current user and redirect to login."""
    auth_logout(request)
    return redirect("login")


@login_required(login_url="login")
@ensure_csrf_cookie
def index(request: HttpRequest) -> HttpResponse:
    """Render the main single-page interview frontend for authenticated users."""
    model_name = get_groq_model_name()
    display_name = request.user.get_full_name() or request.user.username

    return render(
        request,
        "index.html",
        {
            "model_name": model_name,
            "display_name": display_name,
            "username": request.user.username,
        },
    )


@login_required(login_url="login")
@require_POST
def upload_resume(request: HttpRequest) -> JsonResponse:
    """Extract and parse text from an uploaded resume file (PDF, DOCX, TXT)."""
    if "resume_file" not in request.FILES:
        return JsonResponse({"success": False, "error": "No resume file was uploaded."}, status=400)

    uploaded_file = request.FILES["resume_file"]
    extracted_text = parse_resume_file(uploaded_file)

    if extracted_text.startswith("[Error"):
        return JsonResponse({"success": False, "error": extracted_text}, status=400)

    return JsonResponse(
        {
            "success": True,
            "filename": uploaded_file.name,
            "extracted_text": extracted_text,
            "character_count": len(extracted_text),
        }
    )


@login_required(login_url="login")
@require_GET
def get_job_descriptions(request: HttpRequest) -> JsonResponse:
    """Retrieve pre-defined job description templates for popular technical roles."""
    return JsonResponse(
        {
            "success": True,
            "templates": POPULAR_JOB_DESCRIPTIONS,
        }
    )


@login_required(login_url="login")
@require_POST
def start_interview(request: HttpRequest) -> JsonResponse:
    """Initialize a new interview session grounded in resume and job description."""
    session_key = _get_or_create_session_key(request)

    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
    except Exception:
        data = {}

    default_name = request.user.get_full_name() or request.user.username
    candidate_name = data.get("candidate_name", "").strip() or default_name
    target_role = data.get("target_role", "").strip() or "Full Stack Software Engineer"
    num_questions = int(data.get("num_questions", 4))
    if num_questions < 1:
        num_questions = 4

    resume_text = data.get("resume_text", "").strip()
    job_description = data.get("job_description", "").strip()

    # Mark any dangling in-progress sessions for this user as abandoned
    InterviewSession.objects.filter(user=request.user, status="in_progress").update(status="abandoned")

    # Create persistent DB record
    db_session = InterviewSession.objects.create(
        user=request.user,
        candidate_name=candidate_name,
        target_role=target_role,
        total_planned_questions=num_questions,
        resume_text=resume_text,
        job_description=job_description,
        status="in_progress",
    )

    # Setup session state
    state = InterviewState(
        candidate_name=candidate_name,
        target_role=target_role,
        total_planned_questions=num_questions,
        resume_text=resume_text,
        job_description=job_description,
        db_session_id=db_session.id,
    )
    session_states[session_key] = state
    active_session_id.set(session_key)

    try:
        model = create_groq_model()
        evaluator_agent = create_evaluator_agent(
            model=model,
            resume_text=resume_text,
            job_description=job_description,
        )
        interviewer_agent = create_interviewer_agent(
            model=model,
            evaluator_agent=evaluator_agent,
            candidate_name=candidate_name,
            target_role=target_role,
            num_questions=num_questions,
            resume_text=resume_text,
            job_description=job_description,
        )

        agent_session = InMemorySession(session_id=session_key)

        start_prompt = (
            f"Hi! I am {candidate_name}, and I am ready for the interview for the "
            f"{target_role} position. Please introduce yourself and start with the first question "
            f"based on my resume and the job description."
        )

        result = Runner.run_sync(interviewer_agent, start_prompt, session=agent_session)
        current_agent = result.last_agent
        greeting_text = str(result.final_output) if result.final_output else ""

        if db_session.id and greeting_text:
            _persist_chat_message(db_session.id, "agent", current_agent.name, greeting_text)

        interview_sessions[session_key] = {
            "model": model,
            "evaluator_agent": evaluator_agent,
            "interviewer_agent": interviewer_agent,
            "current_agent": current_agent,
            "agent_session": agent_session,
            "candidate_name": candidate_name,
            "target_role": target_role,
            "num_questions": num_questions,
            "resume_loaded": bool(resume_text),
            "jd_loaded": bool(job_description),
            "db_session_id": db_session.id,
            "messages": [
                {
                    "sender": "agent",
                    "agent_name": current_agent.name,
                    "text": greeting_text,
                }
            ],
            "is_completed": False,
        }

        return JsonResponse(
            {
                "success": True,
                "message": greeting_text,
                "agent_name": current_agent.name,
                "candidate_name": candidate_name,
                "target_role": target_role,
                "num_questions": num_questions,
                "resume_loaded": bool(resume_text),
                "jd_loaded": bool(job_description),
                "records": [_serialize_record(r) for r in state.records],
                "is_completed": False,
            }
        )
    except Exception as e:
        logger.exception("Failed to start interview")
        return JsonResponse({"success": False, "error": str(e)}, status=500)


@login_required(login_url="login")
@require_POST
def chat_message(request: HttpRequest) -> JsonResponse:
    """Process candidate's message and return agent's response."""
    session_key = _get_or_create_session_key(request)
    session_info = interview_sessions.get(session_key)

    if not session_info:
        return JsonResponse(
            {"success": False, "error": "No active interview session found. Please start an interview first."},
            status=400,
        )

    try:
        data = json.loads(request.body.decode("utf-8")) if request.body else {}
        user_message = data.get("message", "").strip()
    except Exception:
        user_message = ""

    if not user_message:
        return JsonResponse({"success": False, "error": "Message cannot be empty."}, status=400)

    # Set thread context to current session key
    active_session_id.set(session_key)

    # Record user message in history
    session_info["messages"].append(
        {
            "sender": "user",
            "agent_name": session_info["candidate_name"],
            "text": user_message,
        }
    )

    db_id = session_info.get("db_session_id") or session_states.get(session_key, InterviewState()).db_session_id
    if db_id:
        _persist_chat_message(db_id, "user", session_info["candidate_name"], user_message)

    current_agent = session_info["current_agent"]
    agent_session = session_info["agent_session"]
    state = session_states.get(session_key, InterviewState())
    num_questions = session_info.get("num_questions", 4)
    current_q = min(num_questions, len(state.records) + 1)

    last_agent_question = ""
    for msg in reversed(session_info.get("messages", [])):
        if msg.get("sender") == "agent":
            last_agent_question = msg.get("text", "")
            break

    is_skip = False
    if current_agent.name == "InterviewerAgent":
        lower_msg = user_message.lower().strip()
        if any(kw in lower_msg for kw in ["finish", "wrap up", "end interview", "i'm done", "evaluate me"]):
            turn_input = f"{user_message}\n[Candidate requested to finish. Please thank them and hand off to EvaluatorAgent.]"
        elif any(kw in lower_msg for kw in ["skip", "pass on this question", "skip this question", "skip question", "move on to the next question"]):
            is_skip = True
            next_q = current_q + 1
            q_text_clean = (last_agent_question or f"Question {current_q}").replace('"', "'")[:200]
            if current_q < num_questions:
                instruction_note = (
                    f"[Candidate requested to SKIP Question {current_q} of {num_questions}]: {user_message}\n"
                    f"[Instruction: You MUST call `record_question_feedback` with: "
                    f"question_number={current_q}, topic='Skipped Question', "
                    f"candidate_answer_summary='Question skipped by candidate.', "
                    f"score=1, notes='Question skipped by candidate upon request.', "
                    f"question_text=\"{q_text_clean}\". "
                    f"Then acknowledge briefly in 1 sentence and immediately ask **Question {next_q} of {num_questions}:**.]"
                )
            else:
                instruction_note = (
                    f"[Candidate requested to SKIP Question {current_q} of {num_questions}]: {user_message}\n"
                    f"[Instruction: You MUST call `record_question_feedback` with: "
                    f"question_number={current_q}, topic='Skipped Question', "
                    f"candidate_answer_summary='Question skipped by candidate.', "
                    f"score=1, notes='Question skipped by candidate upon request.', "
                    f"question_text=\"{q_text_clean}\". "
                    f"Then thank them and transfer to EvaluatorAgent.]"
                )
            turn_input = instruction_note
        else:
            turn_input = f"[Candidate answering Question {current_q} of {num_questions}]: {user_message}"
    else:
        turn_input = user_message

    try:
        model = create_groq_model()
        session_info["current_agent"].model = model
        session_info["evaluator_agent"].model = model
        session_info["interviewer_agent"].model = model
        current_agent = session_info["current_agent"]

        result = Runner.run_sync(current_agent, turn_input, session=agent_session)
        current_agent = result.last_agent
        session_info["current_agent"] = current_agent

        output_text = str(result.final_output) if result.final_output else ""
        is_completed = current_agent.name == "EvaluatorAgent"

        # If handed off to EvaluatorAgent but report not yet printed, generate it directly
        if is_completed and "Executive Summary" not in output_text:
            try:
                eval_prompt = (
                    "Please call `get_interview_progress` to review answers, call `record_evaluation_scorecard` with the strictly calculated scores, and output the comprehensive interview evaluation report now."
                )
                eval_res = Runner.run_sync(
                    session_info["evaluator_agent"],
                    eval_prompt,
                    session=agent_session,
                )
                if eval_res.final_output:
                    output_text = (
                        f"{output_text}\n\n{eval_res.final_output}"
                        if output_text
                        else str(eval_res.final_output)
                    )
            except Exception as eval_err:
                logger.warning(f"Failed secondary evaluator run: {eval_err}")

        session_info["is_completed"] = is_completed

        session_info["messages"].append(
            {
                "sender": "agent",
                "agent_name": current_agent.name,
                "text": output_text,
            }
        )

        db_id = session_info.get("db_session_id") or state.db_session_id
        if db_id and output_text:
            _persist_chat_message(db_id, "agent", current_agent.name, output_text, is_completed)

        state = session_states.get(session_key, InterviewState())

        # If user skipped, ensure Question current_q is recorded in state even if agent failed to call tool
        if is_skip and not any(r.question_number == current_q for r in state.records):
            state.add_record(
                question_number=current_q,
                topic="Skipped Question",
                candidate_answer_summary="Question skipped by candidate.",
                score=1,
                notes="Question skipped by candidate upon request.",
                question_text=last_agent_question or f"Question {current_q}",
            )

        for r in state.records:
            if r.question_number == current_q:
                if not getattr(r, "question_text", "") and last_agent_question:
                    r.question_text = last_agent_question
                if not getattr(r, "candidate_answer_summary", ""):
                    r.candidate_answer_summary = "Question skipped by candidate." if is_skip else user_message
                state._persist_record_to_db(r)

        scorecard = _get_effective_scorecard(state)

        if is_completed:
            db_id = session_info.get("db_session_id") or state.db_session_id
            _generate_ideal_answers_for_session(
                db_id,
                state,
                session_info.get("target_role", "Software Engineer"),
                session_info.get("job_description", ""),
            )
            _persist_scorecard_and_completion(db_id, scorecard, output_text)

        return JsonResponse(
            {
                "success": True,
                "message": output_text,
                "agent_name": current_agent.name,
                "is_completed": is_completed,
                "records": [_serialize_record(r) for r in state.records],
                "scorecard": scorecard,
            }
        )
    except Exception as e:
        logger.exception("Error executing agent turn")
        return JsonResponse({"success": False, "error": str(e)}, status=500)


def _generate_ideal_answers_for_session(
    db_session_id: Any,
    state: InterviewState,
    target_role: str = "Software Engineer",
    job_description: str = "",
) -> None:
    """Generate authoritative ideal/benchmark answers for all interview questions evaluated."""
    if not state or not state.records:
        return

    unanswered_records = [r for r in state.records if not getattr(r, "ideal_answer", "")]
    if not unanswered_records:
        return

    try:
        api_key = get_groq_api_key()
        model_name = get_groq_model_name()
        client = OpenAI(api_key=api_key, base_url=GROQ_BASE_URL)

        q_items = []
        for r in unanswered_records:
            q_text = getattr(r, "question_text", "") or f"Interview question regarding {r.topic}"
            c_ans = getattr(r, "candidate_answer_summary", "") or "No response provided"
            q_items.append(
                f"Question {r.question_number} (Topic: {r.topic}):\n"
                f"Question Text: {q_text}\n"
                f"Candidate's Answer: {c_ans}\n"
                f"Score Given: {r.score}/10"
            )

        system_prompt = (
            f"You are a Principal Engineering Director and Senior Hiring Committee Lead conducting technical interviews for the position of '{target_role}'.\n"
            "Your task is to provide the authoritative, comprehensive ideal benchmark answer ('the right answer') for each interview question.\n"
            "Each ideal answer must be clear, well-structured, and practical. It should include:\n"
            "- Core Technical Principle & Direct Answer\n"
            "- Best Practice / Architecture / Production Considerations\n"
            "- Key Takeaways & What Differentiates an Exceptional Answer\n\n"
            "Output strictly a JSON object with this exact format:\n"
            "{\n"
            '  "answers": [\n'
            "    {\n"
            '      "question_number": 1,\n'
            '      "ideal_answer": "### Core Answer\\n...\\n\\n### Key Technical Points\\n- Point 1...\\n\\n### Production Best Practices & Trade-offs\\n..."\n'
            "    }\n"
            "  ]\n"
            "}"
        )

        user_content = (
            f"Target Role: {target_role}\n"
            + (f"Job Description Context:\n{job_description[:1200]}\n\n" if job_description else "")
            + "Questions to provide ideal benchmark answers for:\n\n"
            + "\n\n---\n\n".join(q_items)
        )

        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )

        raw_content = response.choices[0].message.content or "{}"
        parsed = json.loads(raw_content)
        answers_list = parsed.get("answers", [])
        answers_map = {
            a.get("question_number"): a.get("ideal_answer", "")
            for a in answers_list
            if isinstance(a, dict) and "question_number" in a
        }

        for r in state.records:
            if r.question_number in answers_map and answers_map[r.question_number]:
                r.ideal_answer = answers_map[r.question_number]
                if db_session_id:
                    InterviewQuestionRecord.objects.filter(
                        session_id=db_session_id, question_number=r.question_number
                    ).update(ideal_answer=r.ideal_answer)
    except Exception as e:
        logger.warning(f"Failed to generate ideal answers for session: {e}")


def _persist_scorecard_and_completion(
    db_session_id: Any, scorecard: Dict[str, Any], report_markdown: str = ""
) -> None:
    """Persist final scorecard and mark the interview session as completed in database."""
    if not db_session_id:
        return
    try:
        defaults = {
            "verdict": scorecard.get("verdict", "PENDING"),
            "overall_score": scorecard.get("overall_score", 0),
            "competencies": scorecard.get("competencies", {}),
            "key_quote": scorecard.get("key_quote", ""),
            "strong_moments": scorecard.get("strong_moments", []),
            "growth_areas": scorecard.get("growth_areas", []),
            "executive_summary": scorecard.get("executive_summary", ""),
        }
        if report_markdown:
            defaults["full_report_markdown"] = report_markdown

        InterviewScorecard.objects.update_or_create(
            session_id=db_session_id,
            defaults=defaults,
        )
        InterviewSession.objects.filter(id=db_session_id).update(status="completed")
    except Exception as e:
        logger.warning(f"Failed to persist scorecard and completion to DB: {e}")


def _persist_chat_message(
    db_session_id: Any,
    sender: str,
    agent_name: str,
    text: str,
    is_evaluation: bool = False,
):
    """Persist an individual chat message into the database."""
    if not db_session_id:
        return
    try:
        InterviewChatMessage.objects.create(
            session_id=db_session_id,
            sender=sender,
            agent_name=agent_name,
            text=text,
            is_evaluation=is_evaluation,
        )
    except Exception as e:
        logger.warning(f"Failed to persist chat message to DB: {e}")



def _get_effective_scorecard(state: InterviewState) -> Dict[str, Any]:
    """Return structured scorecard, generating an accurate completion-adjusted scorecard if needed."""
    if state.scorecard and state.records:
        return state.scorecard

    total_planned = max(1, state.total_planned_questions)
    completed = len(state.records)

    if not state.records or completed == 0:
        zero_scorecard = {
            "verdict": "NO HIRE",
            "overall_score": 0,
            "competencies": {
                "technical_mastery": 0,
                "system_architecture": 0,
                "problem_solving": 0,
                "communication": 0,
            },
            "key_quote": "",
            "strong_moments": ["No responses submitted."],
            "growth_areas": ["Complete interview questions to receive technical feedback."],
            "executive_summary": f"Interview concluded early with 0 of {total_planned} questions answered. No technical responses were recorded.",
        }
        state.scorecard = zero_scorecard
        return zero_scorecard

    # Prorated score accounting for completion
    earned_points = sum(r.score for r in state.records)
    max_points = total_planned * 10
    prorated_score = max(0, min(100, int((earned_points / max_points) * 100)))
    avg_answered = sum(r.score for r in state.records) / completed

    # Verdict takes completion into account
    if completed < total_planned * 0.5:
        verdict = "NO HIRE"
    elif completed < total_planned:
        verdict = "MAYBE" if prorated_score >= 50 else "NO HIRE"
    else:
        if prorated_score >= 85:
            verdict = "STRONG HIRE"
        elif prorated_score >= 70:
            verdict = "HIRE"
        elif prorated_score >= 55:
            verdict = "MAYBE"
        else:
            verdict = "NO HIRE"

    completion_factor = completed / total_planned
    scorecard = {
        "verdict": verdict,
        "overall_score": prorated_score,
        "competencies": {
            "technical_mastery": max(0, min(100, int(avg_answered * 10 * completion_factor))),
            "system_architecture": max(0, min(100, int(avg_answered * 10 * completion_factor))),
            "problem_solving": max(0, min(100, int(avg_answered * 10 * completion_factor))),
            "communication": max(0, min(100, int(avg_answered * 10))),
        },
        "key_quote": state.records[0].candidate_answer_summary if state.records else "",
        "strong_moments": [f"Demonstrated competence in {r.topic}" for r in state.records if r.score >= 7][:3] or ["Participated in interview."],
        "growth_areas": ([f"Further depth recommended in {r.topic}" for r in state.records if r.score < 7][:3] +
                         ([f"Completed only {completed} of {total_planned} questions."] if completed < total_planned else []))[:3],
        "executive_summary": (
            f"Candidate completed {completed} of {total_planned} questions with an earned score of "
            f"{prorated_score}/100 (average on answered questions: {avg_answered:.1f}/10)."
            + (" Session ended early." if completed < total_planned else "")
        ),
    }
    state.scorecard = scorecard
    return scorecard


@login_required(login_url="login")
@require_POST
def finish_interview(request: HttpRequest) -> JsonResponse:
    """Prompt immediate generation of evaluation report by EvaluatorAgent."""
    session_key = _get_or_create_session_key(request)
    session_info = interview_sessions.get(session_key)

    if not session_info:
        return JsonResponse(
            {"success": False, "error": "No active interview session found."},
            status=400,
        )

    active_session_id.set(session_key)
    evaluator_agent = session_info["evaluator_agent"]
    agent_session = session_info["agent_session"]
    state = session_states.get(session_key, InterviewState())

    # Fast guard for empty sessions: Prevent hallucinating answers if 0 questions answered
    if not state.records:
        zero_scorecard = _get_effective_scorecard(state)
        output_text = (
            "# Vettora Interview Evaluation Report\n\n"
            "## 1. Executive Summary & Verdict\n"
            "**Verdict:** **NO HIRE (INCOMPLETE)** &bull; **Overall Score:** **0/100**\n\n"
            "The interview was concluded early before any technical questions were answered. "
            "No candidate responses were recorded to evaluate competencies.\n\n"
            "## 2. Competency Ratings (0-100)\n"
            "| Competency | Score | Evaluation |\n"
            "|---|---|---|\n"
            "| Technical Mastery | 0/100 | Incomplete (No responses submitted) |\n"
            "| System Architecture | 0/100 | Incomplete (No responses submitted) |\n"
            "| Problem Solving | 0/100 | Incomplete (No responses submitted) |\n"
            "| Communication Clarity | 0/100 | Incomplete (No responses submitted) |\n\n"
            "## 3. Next Steps\n"
            "Please start a new interview session and submit answers to the questions to receive an official evaluation."
        )

        session_info["is_completed"] = True
        session_info["current_agent"] = evaluator_agent
        session_info["messages"].append(
            {
                "sender": "agent",
                "agent_name": evaluator_agent.name,
                "text": output_text,
            }
        )

        db_id = session_info.get("db_session_id") or state.db_session_id
        if db_id and output_text:
            _persist_chat_message(db_id, "agent", evaluator_agent.name, output_text, True)
        _persist_scorecard_and_completion(db_id, zero_scorecard, output_text)

        return JsonResponse(
            {
                "success": True,
                "message": output_text,
                "agent_name": evaluator_agent.name,
                "is_completed": True,
                "records": [],
                "scorecard": zero_scorecard,
            }
        )

    completed = len(state.records)
    total = state.total_planned_questions
    finish_prompt = (
        f"The candidate has concluded the interview. Exactly {completed} of {total} planned questions "
        "were answered and recorded.\n"
        "1. Call `get_interview_progress` to review evaluated responses.\n"
        "2. Call `record_evaluation_scorecard` with the strictly calculated score matching the progress data. "
        "IMPORTANT: Do NOT invent fake quotes or fake answers for any unanswered questions. "
        "If the interview was ended early, reflect the incomplete completion in the verdict and scores.\n"
        "3. Output the official Vettora evaluation report markdown."
    )

    try:
        model = create_groq_model()
        evaluator_agent.model = model
        if "interviewer_agent" in session_info:
            session_info["interviewer_agent"].model = model
        if "current_agent" in session_info:
            session_info["current_agent"].model = model

        result = Runner.run_sync(evaluator_agent, finish_prompt, session=agent_session)
        current_agent = result.last_agent
        session_info["current_agent"] = current_agent

        output_text = str(result.final_output) if result.final_output else ""
        session_info["is_completed"] = True

        session_info["messages"].append(
            {
                "sender": "agent",
                "agent_name": current_agent.name,
                "text": output_text,
            }
        )

        state = session_states.get(session_key, InterviewState())
        scorecard = _get_effective_scorecard(state)

        db_id = session_info.get("db_session_id") or state.db_session_id
        if db_id and output_text:
            _persist_chat_message(db_id, "agent", current_agent.name, output_text, True)

        _generate_ideal_answers_for_session(
            db_id,
            state,
            session_info.get("target_role", "Software Engineer"),
            session_info.get("job_description", ""),
        )
        _persist_scorecard_and_completion(db_id, scorecard, output_text)

        return JsonResponse(
            {
                "success": True,
                "message": output_text,
                "agent_name": current_agent.name,
                "is_completed": True,
                "records": [_serialize_record(r) for r in state.records],
                "scorecard": scorecard,
            }
        )
    except Exception as e:
        logger.exception("Error wrapping up interview")
        return JsonResponse({"success": False, "error": str(e)}, status=500)


@login_required(login_url="login")
@require_GET
def get_status(request: HttpRequest) -> JsonResponse:
    """Retrieve the current interview session status, messages, and scorecards."""
    session_key = _get_or_create_session_key(request)
    session_info = interview_sessions.get(session_key)

    if not session_info:
        active_db = (
            InterviewSession.objects.filter(user=request.user, status="in_progress")
            .order_by("-created_at")
            .first()
        )
        if active_db:
            state = InterviewState(
                candidate_name=request.user.get_full_name() or request.user.username,
                target_role=active_db.target_role,
                total_planned_questions=active_db.total_planned_questions,
                resume_text=active_db.resume_text,
                job_description=active_db.job_description,
                db_session_id=active_db.id,
            )
            for q_rec in active_db.records.all():
                state.records.append(
                    QuestionRecord(
                        question_number=q_rec.question_number,
                        topic=q_rec.topic,
                        candidate_answer_summary=q_rec.candidate_answer,
                        score=q_rec.score,
                        notes=q_rec.interviewer_notes,
                        question_text=q_rec.question_text,
                        ideal_answer=q_rec.ideal_answer,
                    )
                )
            session_states[session_key] = state
            try:
                model = create_groq_model()
                evaluator_agent = create_evaluator_agent(
                    model=model,
                    resume_text=state.resume_text,
                    job_description=state.job_description,
                )
                interviewer_agent = create_interviewer_agent(
                    model=model,
                    evaluator_agent=evaluator_agent,
                    candidate_name=state.candidate_name,
                    target_role=state.target_role,
                    num_questions=state.total_planned_questions,
                    resume_text=state.resume_text,
                    job_description=state.job_description,
                )
                agent_session = InMemorySession(session_id=session_key)
                session_info = {
                    "model": model,
                    "evaluator_agent": evaluator_agent,
                    "interviewer_agent": interviewer_agent,
                    "current_agent": interviewer_agent,
                    "agent_session": agent_session,
                    "candidate_name": state.candidate_name,
                    "target_role": state.target_role,
                    "num_questions": state.total_planned_questions,
                    "resume_loaded": bool(state.resume_text),
                    "jd_loaded": bool(state.job_description),
                    "db_session_id": active_db.id,
                    "messages": [],
                    "is_completed": False,
                }
                interview_sessions[session_key] = session_info
            except Exception as e:
                logger.warning(f"Could not recreate agent session from DB: {e}")

    if not session_info:
        return JsonResponse(
            {"has_active_session": False},
        )

    state = session_states.get(session_key, InterviewState())

    return JsonResponse(
        {
            "has_active_session": True,
            "candidate_name": session_info["candidate_name"],
            "target_role": session_info["target_role"],
            "num_questions": session_info["num_questions"],
            "current_agent": session_info["current_agent"].name,
            "resume_loaded": bool(state.resume_text),
            "jd_loaded": bool(state.job_description),
            "is_completed": session_info["is_completed"],
            "messages": session_info["messages"],
            "records": [_serialize_record(r) for r in state.records],
            "scorecard": _get_effective_scorecard(state),
        }
    )


@login_required(login_url="login")
def list_interview_history(request: HttpRequest) -> JsonResponse:
    """List previous interview sessions for the logged in user."""
    session_key = _get_or_create_session_key(request)
    current_session = interview_sessions.get(session_key)
    current_db_id = current_session.get("db_session_id") if current_session else None

    qs = InterviewSession.objects.filter(user=request.user).select_related("scorecard").prefetch_related("chat_messages")
    sessions_list = []
    for s in qs[:50]:
        sc = getattr(s, "scorecard", None)
        verdict = sc.verdict if sc else ("COMPLETED" if s.status == "completed" else "IN PROGRESS")
        overall_score = sc.overall_score if sc else (None if s.status != "completed" else 0)
        sessions_list.append(
            {
                "id": s.id,
                "candidate_name": s.candidate_name,
                "target_role": s.target_role,
                "status": s.status,
                "total_planned_questions": s.total_planned_questions,
                "created_at": s.created_at.strftime("%b %d, %Y %I:%M %p"),
                "verdict": verdict,
                "overall_score": overall_score,
                "message_count": s.chat_messages.count(),
                "is_active": (s.id == current_db_id),
            }
        )
    return JsonResponse({"success": True, "sessions": sessions_list})


@login_required(login_url="login")
def get_interview_history_detail(request: HttpRequest, session_id: int) -> JsonResponse:
    """Retrieve full details, chat messages, and scorecard of a specific past session."""
    if request.method == "DELETE":
        return delete_interview_session(request, session_id)

    session_obj = InterviewSession.objects.filter(user=request.user, id=session_id).select_related("scorecard").prefetch_related("chat_messages", "records").first()
    if not session_obj:
        return JsonResponse({"success": False, "error": "Interview session not found."}, status=404)

    msgs = [
        {
            "sender": m.sender,
            "agent_name": m.agent_name,
            "text": m.text,
            "is_evaluation": m.is_evaluation,
            "created_at": m.created_at.strftime("%I:%M %p"),
        }
        for m in session_obj.chat_messages.all()
    ]

    records = [_serialize_record(r) for r in session_obj.records.all()]

    sc_obj = getattr(session_obj, "scorecard", None)
    if sc_obj:
        scorecard_dict = {
            "verdict": sc_obj.verdict,
            "overall_score": sc_obj.overall_score,
            "competencies": sc_obj.competencies or {},
            "key_quote": sc_obj.key_quote or "",
            "strong_moments": sc_obj.strong_moments or [],
            "growth_areas": sc_obj.growth_areas or [],
            "executive_summary": sc_obj.executive_summary or "",
        }
    else:
        scorecard_dict = {
            "verdict": "PENDING",
            "overall_score": 0,
            "competencies": {},
            "key_quote": "",
            "strong_moments": [],
            "growth_areas": [],
            "executive_summary": "",
        }

    return JsonResponse(
        {
            "success": True,
            "id": session_obj.id,
            "candidate_name": session_obj.candidate_name,
            "target_role": session_obj.target_role,
            "status": session_obj.status,
            "num_questions": session_obj.total_planned_questions,
            "resume_loaded": bool(session_obj.resume_text),
            "jd_loaded": bool(session_obj.job_description),
            "is_completed": (session_obj.status == "completed"),
            "messages": msgs,
            "records": records,
            "scorecard": scorecard_dict,
        }
    )


@login_required(login_url="login")
@require_POST
def switch_interview_session(request: HttpRequest, session_id: int) -> JsonResponse:
    """Switch active session to this past session so candidate can view or continue it."""
    session_key = _get_or_create_session_key(request)
    session_obj = InterviewSession.objects.filter(user=request.user, id=session_id).select_related("scorecard").prefetch_related("chat_messages", "records").first()
    if not session_obj:
        return JsonResponse({"success": False, "error": "Interview session not found."}, status=404)

    msgs = [
        {
            "sender": m.sender,
            "agent_name": m.agent_name,
            "text": m.text,
            "is_evaluation": m.is_evaluation,
            "created_at": m.created_at.strftime("%I:%M %p"),
        }
        for m in session_obj.chat_messages.all()
    ]

    records = [
        QuestionRecord(
            question_number=r.question_number,
            topic=r.topic,
            candidate_answer_summary=r.candidate_answer,
            score=r.score,
            notes=r.interviewer_notes,
            question_text=r.question_text,
            ideal_answer=r.ideal_answer,
        )
        for r in session_obj.records.all()
    ]

    sc_obj = getattr(session_obj, "scorecard", None)
    scorecard_dict = {}
    if sc_obj:
        scorecard_dict = {
            "verdict": sc_obj.verdict,
            "overall_score": sc_obj.overall_score,
            "competencies": sc_obj.competencies or {},
            "key_quote": sc_obj.key_quote or "",
            "strong_moments": sc_obj.strong_moments or [],
            "growth_areas": sc_obj.growth_areas or [],
            "executive_summary": sc_obj.executive_summary or "",
        }

    state = InterviewState(
        candidate_name=session_obj.candidate_name,
        target_role=session_obj.target_role,
        total_planned_questions=session_obj.total_planned_questions,
        resume_text=session_obj.resume_text,
        job_description=session_obj.job_description,
        records=records,
        scorecard=scorecard_dict,
        db_session_id=session_obj.id,
    )
    session_states[session_key] = state
    active_session_id.set(session_key)

    model = create_groq_model()
    evaluator_agent = create_evaluator_agent(
        model=model,
        resume_text=session_obj.resume_text,
        job_description=session_obj.job_description,
    )
    interviewer_agent = create_interviewer_agent(
        model=model,
        evaluator_agent=evaluator_agent,
        candidate_name=session_obj.candidate_name,
        target_role=session_obj.target_role,
        num_questions=session_obj.total_planned_questions,
        resume_text=session_obj.resume_text,
        job_description=session_obj.job_description,
    )

    agent_session = InMemorySession(session_id=session_key)
    is_completed = (session_obj.status == "completed")
    current_agent = evaluator_agent if is_completed else interviewer_agent

    interview_sessions[session_key] = {
        "model": model,
        "candidate_name": session_obj.candidate_name,
        "target_role": session_obj.target_role,
        "num_questions": session_obj.total_planned_questions,
        "current_agent": current_agent,
        "evaluator_agent": evaluator_agent,
        "interviewer_agent": interviewer_agent,
        "agent_session": agent_session,
        "is_completed": is_completed,
        "resume_loaded": bool(session_obj.resume_text),
        "jd_loaded": bool(session_obj.job_description),
        "db_session_id": session_obj.id,
        "messages": msgs,
    }

    effective_sc = _get_effective_scorecard(state)
    return JsonResponse(
        {
            "success": True,
            "id": session_obj.id,
            "candidate_name": session_obj.candidate_name,
            "target_role": session_obj.target_role,
            "status": session_obj.status,
            "num_questions": session_obj.total_planned_questions,
            "resume_loaded": bool(session_obj.resume_text),
            "jd_loaded": bool(session_obj.job_description),
            "is_completed": is_completed,
            "messages": msgs,
            "records": [_serialize_record(r) for r in records],
            "scorecard": effective_sc,
        }
    )


@login_required(login_url="login")
def delete_interview_session(request: HttpRequest, session_id: int) -> JsonResponse:
    """Delete a past interview session and its history."""
    session_key = _get_or_create_session_key(request)
    deleted_count, _ = InterviewSession.objects.filter(user=request.user, id=session_id).delete()
    if not deleted_count:
        return JsonResponse({"success": False, "error": "Interview session not found."}, status=404)

    curr = interview_sessions.get(session_key)
    if curr and curr.get("db_session_id") == session_id:
        interview_sessions.pop(session_key, None)
        session_states.pop(session_key, None)

    return JsonResponse({"success": True, "message": "Session deleted."})

