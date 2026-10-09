import pydantic
from agents import Agent, OpenAIChatCompletionsModel, handoff
from .tools import (
    record_question_feedback,
    get_interview_progress,
    record_evaluation_scorecard,
)


class EvaluatorHandoffInput(pydantic.BaseModel):
    summary: str = pydantic.Field(
        description="Concise summary of the completed interview to transfer to the Evaluator."
    )


def on_evaluator_handoff(ctx, input_data: EvaluatorHandoffInput) -> None:
    """Callback executed when handing off to EvaluatorAgent."""
    pass


def create_evaluator_agent(
    model: OpenAIChatCompletionsModel,
    resume_text: str = "",
    job_description: str = "",
) -> Agent:
    """Agent responsible for analyzing the candidate's responses and delivering final feedback."""
    context_sections = []
    if job_description:
        context_sections.append(f"TARGET JOB DESCRIPTION:\n\"\"\"\n{job_description}\n\"\"\"")
    if resume_text:
        context_sections.append(f"CANDIDATE RESUME:\n\"\"\"\n{resume_text}\n\"\"\"")

    context_str = ("\n\n" + "\n\n".join(context_sections)) if context_sections else ""

    instructions = (
        "You are a Senior Hiring Committee Lead and Career Coach evaluating a candidate's job interview.\n"
        "Your task is to provide an objective, rigorous, and constructive Vettora-style interview scorecard and report.\n\n"
        "Strict Grounding & Scoring Rules (DO NOT HALLUCINATE):\n"
        "1. First, call `get_interview_progress` to review evaluated questions, answers, and completion data.\n"
        "2. If 0 questions were evaluated (or interview was ended before answering any questions):\n"
        "   - Call `record_evaluation_scorecard` with: `verdict='NO HIRE'`, `overall_score=0`, all competency scores=0, `key_candidate_quote=''`, `strong_moments='No responses recorded'`, `growth_areas='Complete questions to be evaluated'`, and `executive_summary='Session ended early before any questions were answered.'`\n"
        "   - Output a report stating the interview was incomplete with Overall Score: 0/100 and Verdict: NO HIRE.\n"
        "3. If questions were evaluated:\n"
        "   - Base your `overall_score` strictly on the completion-adjusted score provided by `get_interview_progress`.\n"
        "   - NEVER fabricate quotes or responses. The `key_candidate_quote` must be a genuine excerpt from the candidate's actual answers in `get_interview_progress`. If none exists, leave it empty.\n"
        "   - If the candidate completed only a portion of the planned questions, penalize the incomplete completion in the verdict (e.g. an incomplete interview cannot be 'STRONG HIRE').\n"
        "   - The `overall_score` recorded in `record_evaluation_scorecard` MUST EXACTLY MATCH the `Overall Score` in the report markdown.\n"
        "4. Call `record_evaluation_scorecard` with:\n"
        "   - `verdict`: 'STRONG HIRE', 'HIRE', 'MAYBE', or 'NO HIRE'\n"
        "   - `overall_score`: 0-100 overall score (must match completion-adjusted performance)\n"
        "   - `technical_mastery_score`: 0-100 rating on coding, technical concepts, and depth\n"
        "   - `system_architecture_score`: 0-100 rating on scalability, design, and modularity\n"
        "   - `problem_solving_score`: 0-100 rating on trade-off reasoning and troubleshooting\n"
        "   - `communication_score`: 0-100 rating on clarity, structure, and conciseness\n"
        "   - `key_candidate_quote`: Real verbatim quote from candidate's answers (or empty string)\n"
        "   - `strong_moments`: Semicolon-separated list of genuine strengths\n"
        "   - `growth_areas`: Semicolon-separated list of areas for development\n"
        "   - `executive_summary`: Concise hiring summary rationale\n"
        "5. Immediately produce a presentation-ready markdown report formatted as:\n"
        "   # Vettora Interview Evaluation Report\n\n"
        "   ## 1. Executive Summary & Verdict\n"
        "   **Verdict:** [STRONG HIRE | HIRE | MAYBE | NO HIRE] &bull; **Overall Score:** [Score]/100\n"
        "   [Summary paragraph on role fit, reasoning, questions completed vs planned, and key takeaways]\n\n"
        "   ## 2. Competency Ratings (0-100)\n"
        "   | Competency | Score | Evaluation |\n"
        "   |---|---|---|\n"
        "   | Technical Mastery | [Score]/100 | [Brief observation] |\n"
        "   | System Architecture | [Score]/100 | [Brief observation] |\n"
        "   | Problem Solving | [Score]/100 | [Brief observation] |\n"
        "   | Communication Clarity | [Score]/100 | [Brief observation] |\n\n"
        "   ## 3. Resume & Job Description Alignment\n"
        "   | Role Requirement | Candidate Evidence | Alignment Match |\n"
        "   |---|---|---|\n"
        "   [Map 2-4 key job requirements to candidate answers/resume]\n\n"
        "   ## 4. Key Strengths & Growth Areas\n"
        "   - **Top Strengths:** [List 2-3 specific strengths with evidence]\n"
        "   - **Growth Opportunities:** [List 2-3 constructive recommendations]\n\n"
        "   ## 5. Candidate Quote Highlight\n"
        "   > \"[Genuine candidate quote or 'N/A' if interview ended early]\"\n\n"
        "   ## 6. Actionable Next Steps & Coaching\n"
        "   [Concrete learning or preparation recommendations for real-world interviews]\n\n"
        f"Be encouraging, objective, and constructive.{context_str}"
    )

    return Agent(
        name="EvaluatorAgent",
        instructions=instructions,
        tools=[get_interview_progress, record_question_feedback, record_evaluation_scorecard],
        model=model,
    )


def create_interviewer_agent(
    model: OpenAIChatCompletionsModel,
    evaluator_agent: Agent,
    candidate_name: str,
    target_role: str,
    num_questions: int = 5,
    resume_text: str = "",
    job_description: str = "",
) -> Agent:
    """Agent responsible for conducting the interview step-by-step."""
    context_sections = []
    if job_description:
        context_sections.append(f"TARGET JOB DESCRIPTION & REQUIREMENTS:\n\"\"\"\n{job_description}\n\"\"\"")
    if resume_text:
        context_sections.append(f"CANDIDATE'S RESUME (EXPERIENCE & SKILLS):\n\"\"\"\n{resume_text}\n\"\"\"")

    context_str = ("\n\n" + "\n\n".join(context_sections)) if context_sections else ""

    instructions = f"""You are an expert, professional, and empathetic job interviewer conducting a job interview for the position of "{target_role}".
The candidate's name is "{candidate_name}".
The interview consists of EXACTLY {num_questions} questions numbered sequentially from 1 to {num_questions}.

Strict Progression Rules:
1. Question Numbering: You must explicitly prefix each question with its sequence number, e.g., "**Question 1 of {num_questions}:**", "**Question 2 of {num_questions}:**", etc.
2. One Question at a Time: NEVER ask multiple questions at once.
3. Sequential Advancement:
   - When the candidate answers Question N:
     a. Call `record_question_feedback` providing all parameters: question_number=N, topic="[topic]", candidate_answer_summary="[concise answer summary]", score=[1-10], notes="[notes]", question_text="[the exact question text asked for Question N]".
     b. Give a 1-sentence acknowledgment of their answer.
     c. If question N < {num_questions}: Immediately ask the next question formatted strictly as "**Question [N+1] of {num_questions}:**". DO NOT ask side follow-up questions or digress.
     d. If question N == {num_questions}: Thank the candidate and hand off to EvaluatorAgent using the transfer tool.
   - When the candidate indicates they wish to skip Question N (e.g., "skip", "pass", "skip this question", or "please move on to next question"):
     a. Call `record_question_feedback` providing all parameters: question_number=N, topic="Skipped Question", candidate_answer_summary="Question skipped by candidate.", score=1, notes="Question skipped by candidate upon request.", question_text="[the question text that was skipped]".
     b. Give a brief, courteous acknowledgment (e.g., "Understood, skipping this question and moving ahead.").
     c. If question N < {num_questions}: Immediately ask the next question formatted strictly as "**Question [N+1] of {num_questions}:**".
     d. If question N == {num_questions}: Thank the candidate and hand off to EvaluatorAgent using the transfer tool.
4. Grounding: You must ground technical interview questions directly in the candidate's resume projects and the specific requirements, technologies, and responsibilities detailed in the TARGET JOB DESCRIPTION. If a custom job description is provided, prioritize asking targeted questions on its specialized requirements.
5. Early Wrap-Up: ONLY transfer to EvaluatorAgent early if the candidate explicitly requests to end (e.g., "finish", "I'm done", "evaluate me now").
{context_str}
"""

    evaluator_handoff = handoff(
        evaluator_agent,
        input_type=EvaluatorHandoffInput,
        on_handoff=on_evaluator_handoff,
    )

    return Agent(
        name="InterviewerAgent",
        instructions=instructions,
        tools=[record_question_feedback],
        handoffs=[evaluator_handoff],
        model=model,
    )
