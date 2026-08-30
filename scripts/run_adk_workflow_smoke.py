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

APP_NAME = "appointment_agent_workflow_smoke"
USER_ID = "workflow_smoke_user"
SESSION_ID = "workflow_smoke_session"
STATE_KEY = "appointment_workflow"
EXPECTED_FLOW = [
    "requested",
    "contacting",
    "awaiting_reply",
    "retry_due",
    "contacting",
    "time_proposed",
    "awaiting_human_approval",
    "confirmed",
]


def validate_environment() -> None:
    required = {
        "GOOGLE_CLOUD_PROJECT": os.getenv("GOOGLE_CLOUD_PROJECT", "").strip(),
        "GOOGLE_CLOUD_LOCATION": os.getenv("GOOGLE_CLOUD_LOCATION", "").strip(),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError("Missing required environment variables: " + ", ".join(missing))
    if required["GOOGLE_CLOUD_PROJECT"] == "your-project-id":
        raise RuntimeError("GOOGLE_CLOUD_PROJECT still contains the placeholder value.")
    if os.getenv("GOOGLE_GENAI_USE_ENTERPRISE", "").strip().upper() != "TRUE":
        raise RuntimeError("GOOGLE_GENAI_USE_ENTERPRISE must be TRUE.")


async def run_turn(runner: Runner, prompt: str) -> tuple[list[str], str]:
    tools: list[str] = []
    final_text = ""
    message = types.Content(role="user", parts=[types.Part(text=prompt)])
    async for event in runner.run_async(
        user_id=USER_ID,
        session_id=SESSION_ID,
        new_message=message,
    ):
        tools.extend(call.name for call in event.get_function_calls())
        if event.is_final_response() and event.content:
            final_text = "".join(
                part.text or ""
                for part in event.content.parts or []
                if getattr(part, "text", None)
            ).strip()
    return tools, final_text


async def get_snapshot(session_service: InMemorySessionService) -> dict:
    session = await session_service.get_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=SESSION_ID,
    )
    if session is None or STATE_KEY not in session.state:
        raise RuntimeError("ADK session has no appointment workflow snapshot.")
    return session.state[STATE_KEY]


async def run_smoke() -> None:
    validate_environment()
    from appointment_agent.agent import MODEL_NAME, root_agent

    session_service = InMemorySessionService()
    await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=SESSION_ID,
    )
    runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=session_service)

    try:
        turn1_tools, turn1_text = await run_turn(
            runner,
            "Use the mock AC repair scenario to arrange an appointment. "
            "Stop and ask me before confirming any time.",
        )
        snapshot = await get_snapshot(session_service)
        if "run_appointment_to_approval" not in turn1_tools:
            raise RuntimeError("Turn 1 did not call run_appointment_to_approval.")
        if "confirm_appointment" in turn1_tools:
            raise RuntimeError("Turn 1 called confirm_appointment before approval.")
        if snapshot.get("request_state") != "awaiting_human_approval":
            raise RuntimeError("Turn 1 did not stop at awaiting_human_approval.")
        slots = snapshot.get("available_slots", [])
        if len(slots) != 2:
            raise RuntimeError("Turn 1 snapshot does not contain two proposal slots.")
        if not turn1_text:
            raise RuntimeError("Turn 1 returned no final text.")
        if not any(slot in turn1_text for slot in slots):
            raise RuntimeError("Turn 1 response did not present a proposal slot.")

        approved_slot = slots[0]
        turn2_tools, turn2_text = await run_turn(
            runner,
            f"I approve {approved_slot}. Confirm it.",
        )
        snapshot = await get_snapshot(session_service)
        if "confirm_appointment" not in turn2_tools:
            raise RuntimeError("Turn 2 did not call confirm_appointment.")
        if snapshot.get("request_state") != "confirmed":
            raise RuntimeError("Turn 2 did not reach confirmed.")
        if snapshot.get("selected_slot") != approved_slot:
            raise RuntimeError("Confirmed slot does not match the approved slot.")
        if not snapshot.get("appointment_id"):
            raise RuntimeError("Confirmed snapshot has no appointment_id.")
        if not turn2_text:
            raise RuntimeError("Turn 2 returned no final text.")

        events = snapshot["store_state"]["events"]
        flow = [events[0]["from_state"]] + [event["to_state"] for event in events]
        if flow != EXPECTED_FLOW:
            raise RuntimeError(f"Unexpected transition flow: {' -> '.join(flow)}")
    finally:
        await runner.close()

    all_tools = turn1_tools + turn2_tools
    print("ADK two-turn workflow smoke test: PASS")
    print(f"Model: {MODEL_NAME}")
    print("Tools: " + " -> ".join(all_tools))
    print("Flow: " + " -> ".join(EXPECTED_FLOW))
    print(f"Approved slot: {approved_slot}")
    print(f"Appointment: {snapshot['appointment_id']}")


if __name__ == "__main__":
    asyncio.run(run_smoke())
