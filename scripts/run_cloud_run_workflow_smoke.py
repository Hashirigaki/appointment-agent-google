import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

APP_NAME = "appointment_agent"
USER_ID = "cloud_run_smoke_user"
SESSION_ID = f"cloud_run_smoke_{uuid4().hex}"
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


def configuration() -> tuple[str, str]:
    service_url = os.getenv("CLOUD_RUN_SERVICE_URL", "").strip().rstrip("/")
    token = os.getenv("CLOUD_RUN_ID_TOKEN", "").strip()
    if not service_url or not token:
        raise RuntimeError(
            "CLOUD_RUN_SERVICE_URL and CLOUD_RUN_ID_TOKEN are required."
        )
    return service_url, token


def request_json(
    service_url: str,
    token: str,
    method: str,
    path: str,
    payload: dict | None = None,
) -> dict:
    body = json.dumps(payload).encode() if payload is not None else None
    request = Request(
        service_url + path,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=180) as response:
            return json.loads(response.read().decode())
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"Cloud Run API returned HTTP {exc.code}: {detail}") from exc


def run_turn(service_url: str, token: str, prompt: str) -> tuple[list[str], str]:
    payload = {
        "app_name": APP_NAME,
        "user_id": USER_ID,
        "session_id": SESSION_ID,
        "new_message": {"role": "user", "parts": [{"text": prompt}]},
        "streaming": False,
    }
    request = Request(
        service_url + "/run_sse",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    tools: list[str] = []
    final_text = ""
    try:
        with urlopen(request, timeout=300) as response:
            for raw_line in response:
                line = raw_line.decode().strip()
                if not line.startswith("data:"):
                    continue
                event = json.loads(line[5:].strip())
                content = event.get("content") or {}
                for part in content.get("parts") or []:
                    function_call = part.get("functionCall") or part.get("function_call")
                    if function_call and function_call.get("name"):
                        tools.append(function_call["name"])
                    if part.get("text"):
                        final_text = part["text"].strip()
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"Cloud Run API returned HTTP {exc.code}: {detail}") from exc
    return tools, final_text


def session_snapshot(service_url: str, token: str) -> dict:
    session = request_json(
        service_url,
        token,
        "GET",
        f"/apps/{APP_NAME}/users/{USER_ID}/sessions/{SESSION_ID}",
    )
    state = session.get("state") or {}
    if "appointment_workflow" not in state:
        raise RuntimeError("Deployed ADK session has no appointment workflow state.")
    return state["appointment_workflow"]


def main() -> None:
    service_url, token = configuration()
    request_json(
        service_url,
        token,
        "POST",
        f"/apps/{APP_NAME}/users/{USER_ID}/sessions/{SESSION_ID}",
        {"state": {}},
    )

    turn1_tools, turn1_text = run_turn(
        service_url,
        token,
        "Use the mock AC repair scenario to arrange an appointment. "
        "Stop and ask me before confirming any time.",
    )
    first = session_snapshot(service_url, token)
    if "run_appointment_to_approval" not in turn1_tools:
        raise RuntimeError(f"Turn 1 did not call the workflow tool: {turn1_tools}")
    if "confirm_appointment" in turn1_tools:
        raise RuntimeError("Turn 1 confirmed before explicit human approval.")
    if first.get("request_state") != "awaiting_human_approval":
        raise RuntimeError("Turn 1 did not stop at awaiting_human_approval.")
    slots = first.get("available_slots", [])
    if len(slots) != 2 or not turn1_text:
        raise RuntimeError("Turn 1 proposal or final response is incomplete.")

    approved_slot = slots[0]
    turn2_tools, turn2_text = run_turn(
        service_url, token, f"I approve {approved_slot}. Confirm it."
    )
    final = session_snapshot(service_url, token)
    if "confirm_appointment" not in turn2_tools or not turn2_text:
        raise RuntimeError(f"Turn 2 did not call confirmation: {turn2_tools}")
    if final.get("request_state") != "confirmed":
        raise RuntimeError("Deployed workflow did not reach confirmed.")
    if final.get("selected_slot") != approved_slot or not final.get("appointment_id"):
        raise RuntimeError("Deployed confirmation metadata is incomplete.")

    from appointment_agent.state_store import FirestoreStateStore, create_firestore_client

    project = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
    database = os.getenv("FIRESTORE_DATABASE", "(default)").strip()
    collection = os.getenv(
        "FIRESTORE_WORKFLOW_COLLECTION", "appointment_workflow_runs"
    ).strip()
    document = (
        create_firestore_client(project, database)
        .collection(collection)
        .document(final["run_id"])
        .get()
    )
    if not document.exists:
        raise RuntimeError("Cloud Run workflow run is missing from Firestore.")
    canonical = document.to_dict()
    events = canonical["store_state"]["events"]
    flow = [events[0]["from_state"]] + [event["to_state"] for event in events]
    if canonical.get("request_state") != "confirmed" or flow != EXPECTED_FLOW:
        raise RuntimeError(f"Unexpected Firestore flow: {' -> '.join(flow)}")

    trajectory_store = FirestoreStateStore(
        run_id=canonical["run_id"],
        project=project,
        database=database,
        collection=collection,
        trajectory_collection=os.getenv(
            "FIRESTORE_TRAJECTORY_COLLECTION", "trajectories"
        ).strip(),
        event_collection=os.getenv("FIRESTORE_EVENT_COLLECTION", "events").strip(),
        detail_collection=os.getenv("FIRESTORE_DETAIL_COLLECTION", "details").strip(),
    )
    semantic_events = trajectory_store.get_events_for_run(canonical["run_id"])
    request = canonical["store_state"]["objects"]["AppointmentRequest"][
        canonical["request_id"]
    ]
    user_trajectories = trajectory_store.get_trajectories_for_user(
        request["requester_id"]
    )
    if len(semantic_events) < 4 or len(user_trajectories) != 1:
        raise RuntimeError("Deployed v0.2 trajectory queries are incomplete.")

    print("Authenticated Cloud Run workflow smoke test: PASS")
    print("Tools: " + " -> ".join(turn1_tools + turn2_tools))
    print("Flow: " + " -> ".join(flow))
    print(f"Run ID: {final['run_id']}")
    print(f"Appointment: {final['appointment_id']}")
    print(f"Semantic events: {len(semantic_events)}")
    print("Reverse user query: PASS")


if __name__ == "__main__":
    main()
