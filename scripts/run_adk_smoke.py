import asyncio
import os
from pathlib import Path
import sys

from dotenv import load_dotenv
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

APP_NAME = "appointment_agent_smoke"
USER_ID = "smoke_user"
SESSION_ID = "smoke_session"
EXPECTED_TOOLS = {"describe_ontology", "explain_human_boundary"}
PROMPT = (
    "Call both describe_ontology and explain_human_boundary, then briefly "
    "confirm the object types and the human approval boundary."
)


def validate_environment() -> None:
    required = {
        "GOOGLE_CLOUD_PROJECT": os.getenv("GOOGLE_CLOUD_PROJECT", "").strip(),
        "GOOGLE_CLOUD_LOCATION": os.getenv("GOOGLE_CLOUD_LOCATION", "").strip(),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError(
            "Missing required environment variables: " + ", ".join(missing)
        )

    if required["GOOGLE_CLOUD_PROJECT"] == "your-project-id":
        raise RuntimeError("GOOGLE_CLOUD_PROJECT still contains the placeholder value.")

    enterprise = os.getenv("GOOGLE_GENAI_USE_ENTERPRISE", "").strip().upper()
    if enterprise != "TRUE":
        raise RuntimeError("GOOGLE_GENAI_USE_ENTERPRISE must be TRUE.")


async def run_smoke() -> None:
    validate_environment()

    from appointment_agent.agent import MODEL_NAME, root_agent

    session_service = InMemorySessionService()
    await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=SESSION_ID,
    )
    runner = Runner(
        agent=root_agent,
        app_name=APP_NAME,
        session_service=session_service,
    )

    called_tools = set()
    final_text = ""
    message = types.Content(role="user", parts=[types.Part(text=PROMPT)])

    try:
        async for event in runner.run_async(
            user_id=USER_ID,
            session_id=SESSION_ID,
            new_message=message,
        ):
            called_tools.update(call.name for call in event.get_function_calls())
            if event.is_final_response() and event.content:
                final_text = "".join(
                    part.text or ""
                    for part in event.content.parts or []
                    if getattr(part, "text", None)
                ).strip()
    finally:
        await runner.close()

    missing_tools = EXPECTED_TOOLS - called_tools
    if missing_tools:
        raise RuntimeError(
            "Gemini did not call required tools: " + ", ".join(sorted(missing_tools))
        )
    if not final_text:
        raise RuntimeError("Gemini returned no final text.")

    print("ADK Gemini smoke test: PASS")
    print(f"Model: {MODEL_NAME}")
    print("Tools: " + ", ".join(sorted(called_tools)))
    print("Response:")
    print(final_text)


if __name__ == "__main__":
    asyncio.run(run_smoke())
