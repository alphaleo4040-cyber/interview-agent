import os
import sys
from dotenv import load_dotenv
from openai import AsyncOpenAI
from agents import OpenAIChatCompletionsModel, set_tracing_disabled

# Disable tracing to avoid attempts to log to OpenAI's platform
os.environ["OPENAI_AGENTS_DISABLE_TRACING"] = "1"
set_tracing_disabled(True)

# Load environment variables from .env file
load_dotenv(override=True)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "openai/gpt-oss-120b"


def get_groq_api_key() -> str:
    """Retrieve and validate the Groq API key."""
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key or api_key == "your_groq_api_key_here":
        print(
            "\n[Error] GROQ_API_KEY is not set or still contains the placeholder value.\n"
            "Please open .env and set your valid Groq API key: GROQ_API_KEY=gsk_...\n"
            "You can get a free key at https://console.groq.com\n",
            file=sys.stderr,
        )
        sys.exit(1)
    return api_key


def get_groq_model_name() -> str:
    """Retrieve configured Groq model name."""
    return os.getenv("GROQ_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def create_groq_model() -> OpenAIChatCompletionsModel:
    """Instantiate the OpenAI Agents SDK model backed by Groq."""
    api_key = get_groq_api_key()
    model_name = get_groq_model_name()

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=GROQ_BASE_URL,
    )

    return OpenAIChatCompletionsModel(
        model=model_name,
        openai_client=client,
    )
