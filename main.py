import sys

# Ensure UTF-8 output encoding on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

from agents import Runner
from core.config import create_groq_model, get_groq_model_name
from core.session import InMemorySession
from core.tools import interview_state
from core.agents import create_evaluator_agent, create_interviewer_agent

console = Console()



def print_banner(role: str, name: str, questions: int, model_name: str) -> None:
    content = (
        f"[bold cyan]Candidate:[/bold cyan] {name}\n"
        f"[bold cyan]Target Role:[/bold cyan] {role}\n"
        f"[bold cyan]Questions Planned:[/bold cyan] {questions}\n"
        f"[bold cyan]LLM Provider:[/bold cyan] Groq ({model_name})\n"
        f"[bold cyan]Framework:[/bold cyan] OpenAI Agents SDK\n\n"
        "[italic green]Commands:[/italic green]\n"
        " - Type your answer naturally and press Enter.\n"
        " - Type [bold yellow]'finish'[/bold yellow] or [bold yellow]'eval'[/bold yellow] anytime to wrap up and receive your final evaluation.\n"
        " - Type [bold red]'exit'[/bold red] to quit the session."
    )
    console.print(
        Panel(
            content,
            title="[bold green]AI Job Interviewer[/bold green]",
            border_style="bright_blue",
        )
    )


def main() -> None:
    console.print("\n[bold green]=== Welcome to the AI Job Interview Agent ===[/bold green]\n")

    # Candidate and role setup with sensible defaults
    name_input = console.input("[bold yellow]Enter your name [Candidate]: [/bold yellow]").strip()
    candidate_name = name_input if name_input else "Candidate"

    role_input = console.input(
        "[bold yellow]Enter target job role [Full Stack Software Engineer]: [/bold yellow]"
    ).strip()
    target_role = role_input if role_input else "Full Stack Software Engineer"

    q_input = console.input("[bold yellow]Number of questions to practice [4]: [/bold yellow]").strip()
    num_questions = int(q_input) if q_input.isdigit() and int(q_input) > 0 else 4

    # Update shared interview state
    interview_state.candidate_name = candidate_name
    interview_state.target_role = target_role
    interview_state.total_planned_questions = num_questions

    # Initialize model backed by Groq
    groq_model = create_groq_model()
    model_name = get_groq_model_name()

    print_banner(target_role, candidate_name, num_questions, model_name)

    # Create Agents
    evaluator_agent = create_evaluator_agent(groq_model)
    interviewer_agent = create_interviewer_agent(
        model=groq_model,
        evaluator_agent=evaluator_agent,
        candidate_name=candidate_name,
        target_role=target_role,
        num_questions=num_questions,
    )

    # Initialize conversational session
    session = InMemorySession(session_id="interview_session")
    current_agent = interviewer_agent

    # Kick off the interview
    console.print("\n[dim]Initializing interview session...[/dim]\n")
    start_prompt = (
        f"Hi! I am {candidate_name}, and I am ready for the interview for the "
        f"{target_role} position. Please introduce yourself and start with the first question."
    )

    try:
        result = Runner.run_sync(current_agent, start_prompt, session=session)
        current_agent = result.last_agent

        output_text = str(result.final_output) if result.final_output else ""
        console.print(
            Panel(
                Markdown(output_text),
                title=f"[bold green]{current_agent.name}[/bold green]",
                border_style="green",
            )
        )
    except Exception as e:
        console.print(f"[bold red]Failed to start interview:[/bold red] {e}")
        return

    # Main interview interaction loop
    while True:
        try:
            user_input = console.input("\n[bold cyan]You > [/bold cyan]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Session ended by user.[/yellow]")
            break

        if not user_input:
            continue

        if user_input.lower() in ["exit", "quit", "q"]:
            console.print("[yellow]Exiting interview. Good luck with your preparation![/yellow]")
            break

        # Check if user explicitly wants to end early and see the evaluation
        if user_input.lower() in ["finish", "finish interview", "eval", "evaluation", "feedback"]:
            user_input = (
                "I would like to wrap up the interview now. Please hand off to the EvaluatorAgent "
                "to provide my comprehensive evaluation report."
            )

        console.print("[dim]Thinking...[/dim]")

        try:
            result = Runner.run_sync(current_agent, user_input, session=session)
            current_agent = result.last_agent
            output_text = str(result.final_output) if result.final_output else ""

            is_evaluation = current_agent.name == "EvaluatorAgent"
            title = (
                f"[bold magenta]Final Evaluation Report ({current_agent.name})[/bold magenta]"
                if is_evaluation
                else f"[bold green]{current_agent.name}[/bold green]"
            )
            border_color = "magenta" if is_evaluation else "green"

            console.print(
                Panel(
                    Markdown(output_text),
                    title=title,
                    border_style=border_color,
                )
            )

            if is_evaluation:
                console.print(
                    "\n[bold green]Interview completed! You can ask follow-up questions about your feedback or type 'exit' to quit.[/bold green]"
                )

        except Exception as e:
            console.print(f"[bold red]Error running agent:[/bold red] {e}")


if __name__ == "__main__":
    main()
