import asyncio
import os
from pathlib import Path
import sys
from uuid import uuid4

from dotenv import load_dotenv
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.api_core.exceptions import Forbidden, NotFound
from google.genai import types


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")
os.environ["APPOINTMENT_STATE_BACKEND"] = "firestore"

APP_NAME = "appointment_agent_firestore_smoke"
USER_ID = "firestore_smoke_user"
SESSION_ID = f"firestore_smoke_{uuid4().hex}"
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


def settings() -> tuple[str, str, str]:
    project = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
    database = os.getenv("FIRESTORE_DATABASE", "(default)").strip()
    collection = os.getenv(
        "FIRESTORE_WORKFLOW_COLLECTION", "appointment_workflow_runs"
    ).strip()
    if not project or project == "your-project-id":
        raise RuntimeError("A real GOOGLE_CLOUD_PROJECT is required.")
    if os.getenv("GOOGLE_GENAI_USE_ENTERPRISE", "").strip().upper() != "TRUE":
        raise RuntimeError("GOOGLE_GENAI_USE_ENTERPRISE must be TRUE.")
    if os.getenv("GOOGLE_CLOUD_LOCATION", "").strip() != "global":
        raise RuntimeError("GOOGLE_CLOUD_LOCATION must remain global for Gemini.")
    return project, database, collection


def verify_database_exists(project: str, database: str, collection: str) -> None:
    from appointment_agent.state_store import create_firestore_client

    client = create_firestore_client(project=project, database=database)
    try:
        next(iter(client.collection(collection).list_documents(page_size=1)), None)
    except Forbidden as exc:
        if "SERVICE_DISABLED" in str(exc):
            raise RuntimeError(
                f"Cloud Firestore API is disabled in project {project!r}. Enable "
                "firestore.googleapis.com explicitly, then rerun this smoke test. "
                "No cloud resource was changed."
            ) from exc
        raise RuntimeError(
            f"ADC is not authorized to read Firestore in project {project!r}: {exc}"
        ) from exc
    except NotFound as exc:
        raise RuntimeError(
            f"Firestore database {database!r} does not exist in project {project!r}. "
            "Create it explicitly in the required Firestore location, then rerun; "
            "this smoke test does not create cloud resources."
        ) from exc


async def run_turn(runner: Runner, prompt: str) -> tuple[list[str], str]:
    called: list[str] = []
    final_text = ""
    message = types.Content(role="user", parts=[types.Part(text=prompt)])
    async for event in runner.run_async(
        user_id=USER_ID, session_id=SESSION_ID, new_message=message
    ):
        called.extend(call.name for call in event.get_function_calls())
        if event.is_final_response() and event.content:
            final_text = "".join(
                part.text or ""
                for part in event.content.parts or []
                if getattr(part, "text", None)
            ).strip()
    return called, final_text


async def snapshot(session_service: InMemorySessionService) -> dict:
    session = await session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=SESSION_ID
    )
    if session is None or STATE_KEY not in session.state:
        raise RuntimeError("ADK session has no workflow snapshot.")
    return session.state[STATE_KEY]


def verify_no_dangling_references(value: dict) -> None:
    objects = value["store_state"]["objects"]
    requests = objects.get("AppointmentRequest", {})
    attempts = objects.get("ContactAttempt", {})
    proposals = objects.get("TimeProposal", {})
    appointments = objects.get("Appointment", {})
    providers = objects.get("Organization", {})
    contacts = objects.get("ContactPoint", {})
    people = objects.get("Person", {})

    request = requests[value["request_id"]]
    assert request["requester_id"] in people
    assert all(item in providers for item in request["candidate_provider_ids"])
    assert all(item in attempts for item in request["contact_attempt_ids"])
    assert all(item in proposals for item in request["proposal_ids"])
    assert request["selected_provider_id"] in providers
    assert request["appointment_id"] in appointments
    assert value["proposal_id"] in proposals
    assert value["appointment_id"] in appointments
    for contact in contacts.values():
        assert contact["owner_id"] in providers
    for attempt in attempts.values():
        assert attempt["request_id"] in requests
        assert attempt["provider_id"] in providers
        assert attempt["contact_point_id"] in contacts
    for proposal in proposals.values():
        assert proposal["request_id"] in requests
        assert proposal["provider_id"] in providers
    for appointment in appointments.values():
        assert appointment["request_id"] in requests
        assert appointment["requester_id"] in people
        assert appointment["provider_id"] in providers
    for event in value["store_state"]["events"]:
        assert event["request_id"] in requests


async def run_smoke() -> None:
    project, database, collection = settings()
    verify_database_exists(project, database, collection)
    from appointment_agent.agent import MODEL_NAME, root_agent
    from appointment_agent.state_store import create_firestore_client

    sessions = InMemorySessionService()
    await sessions.create_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=SESSION_ID
    )
    runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=sessions)
    try:
        turn1_tools, turn1_text = await run_turn(
            runner,
            "Use the mock AC repair scenario to arrange an appointment. "
            "Stop and ask me before confirming any time.",
        )
        first = await snapshot(sessions)
        if "run_appointment_to_approval" not in turn1_tools:
            raise RuntimeError(f"Turn 1 did not run the workflow: {turn1_tools}")
        if "confirm_appointment" in turn1_tools:
            raise RuntimeError("Turn 1 confirmed before human approval.")
        if first.get("backend") != "firestore" or not first.get("run_id"):
            raise RuntimeError("Turn 1 did not create a Firestore run_id.")
        if first.get("request_state") != "awaiting_human_approval":
            raise RuntimeError("Turn 1 did not stop for human approval.")
        slots = first.get("available_slots", [])
        if len(slots) != 2 or not turn1_text:
            raise RuntimeError("Turn 1 proposal/final response is incomplete.")

        approved_slot = slots[0]
        turn2_tools, turn2_text = await run_turn(
            runner, f"I approve {approved_slot}. Confirm it."
        )
        final = await snapshot(sessions)
        if "confirm_appointment" not in turn2_tools or not turn2_text:
            raise RuntimeError(f"Turn 2 did not confirm successfully: {turn2_tools}")

        persisted = (
            create_firestore_client(project=project, database=database)
            .collection(collection)
            .document(final["run_id"])
            .get()
        )
        if not persisted.exists:
            raise RuntimeError("The Firestore workflow document does not exist.")
        canonical = persisted.to_dict()
        events = canonical["store_state"]["events"]
        flow = [events[0]["from_state"]] + [event["to_state"] for event in events]
        if canonical.get("request_state") != "confirmed":
            raise RuntimeError("Firestore canonical state is not confirmed.")
        if canonical.get("selected_slot") != approved_slot:
            raise RuntimeError("Firestore selected_slot differs from approval.")
        if not canonical.get("appointment_id") or flow != EXPECTED_FLOW:
            raise RuntimeError(f"Invalid Firestore workflow: {' -> '.join(flow)}")
        verify_no_dangling_references(canonical)
    finally:
        await runner.close()

    print("Firestore ADK two-turn workflow smoke test: PASS")
    print(f"Model: {MODEL_NAME}")
    print(f"Database: {database}")
    print(f"Collection: {collection}")
    print(f"Run ID: {canonical['run_id']}")
    print("Tools: " + " -> ".join(turn1_tools + turn2_tools))
    print("Flow: " + " -> ".join(EXPECTED_FLOW))
    print("Dangling references: none")


if __name__ == "__main__":
    asyncio.run(run_smoke())
