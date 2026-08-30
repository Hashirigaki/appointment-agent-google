"""ADK function tools for the deterministic appointment workflow."""

from copy import deepcopy
import json
import os
from pathlib import Path
from typing import Any

from google.adk.tools import ToolContext

from .mock_services import MockRepairProviderService
from .ontology import (
    AppointmentRequest,
    Channel,
    ContactPoint,
    Organization,
    Person,
    RequestState,
    TimeProposal,
    new_id,
    serialize,
)
from .state_store import FirestoreStateStore, JsonStateStore
from .workflow import AppointmentWorkflow


STATE_KEY = "appointment_workflow"
PACKAGE_ROOT = Path(__file__).resolve().parent


def _load_scenario() -> dict[str, Any]:
    path = PACKAGE_ROOT / "data" / "scenario_ac_repair.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _backend_name() -> str:
    backend = os.getenv("APPOINTMENT_STATE_BACKEND", "json").strip().lower()
    if backend not in {"json", "firestore"}:
        raise ValueError("APPOINTMENT_STATE_BACKEND must be 'json' or 'firestore'.")
    return backend


def _new_store(
    run_id: str,
    backend: str,
    state: dict[str, Any] | None = None,
) -> JsonStateStore | FirestoreStateStore:
    if backend == "firestore":
        project = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
        if not project:
            raise ValueError("GOOGLE_CLOUD_PROJECT is required for Firestore persistence.")
        store: JsonStateStore | FirestoreStateStore = FirestoreStateStore(
            run_id=run_id,
            project=project,
            database=os.getenv("FIRESTORE_DATABASE", "(default)").strip(),
            collection=os.getenv(
                "FIRESTORE_WORKFLOW_COLLECTION", "appointment_workflow_runs"
            ).strip(),
        )
    else:
        # ADK session state remains the JSON backend's canonical snapshot.
        store = JsonStateStore(
            str(PACKAGE_ROOT / "data" / "adk_workflow_unused.json")
        )
    if state is not None:
        store.state = deepcopy(state)
    return store


def _snapshot(
    request: AppointmentRequest,
    proposal: TimeProposal,
    store: JsonStateStore | FirestoreStateStore,
    run_id: str,
    backend: str,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "backend": backend,
        "request_id": request.id,
        "proposal_id": proposal.id,
        "request_state": request.state.value,
        "available_slots": list(proposal.slots),
        "selected_slot": request.selected_slot,
        "appointment_id": request.appointment_id,
        "store_state": deepcopy(store.state),
    }


def _approval_result(snapshot: dict[str, Any]) -> dict[str, Any]:
    slots = list(snapshot.get("available_slots", []))
    state = snapshot.get("request_state")
    return {
        "status": "success",
        "run_id": snapshot.get("run_id"),
        "request_id": snapshot.get("request_id"),
        "request_state": state,
        "proposal_id": snapshot.get("proposal_id"),
        "available_slots": slots,
        "requires_human_approval": state == RequestState.AWAITING_HUMAN_APPROVAL.value,
        "message": (
            "Present these provider-proposed slots to the user and wait for explicit "
            "approval before confirming: " + ", ".join(slots)
        ),
    }


def _rehydrate_request(data: dict[str, Any]) -> AppointmentRequest:
    values = deepcopy(data)
    values["state"] = RequestState(values["state"])
    return AppointmentRequest(**values)


def _rehydrate_proposal(data: dict[str, Any]) -> TimeProposal:
    return TimeProposal(**deepcopy(data))


def run_appointment_to_approval(tool_context: ToolContext) -> dict[str, Any]:
    """Run the mock AC repair workflow up to its human approval boundary."""
    existing = tool_context.state.get(STATE_KEY)
    if isinstance(existing, dict):
        if existing.get("backend") == "firestore" and existing.get("run_id"):
            try:
                store = _new_store(existing["run_id"], "firestore")
                persisted = store.load_snapshot()
                if persisted is not None:
                    existing = persisted
                    tool_context.state[STATE_KEY] = deepcopy(existing)
            except Exception as exc:
                return {"status": "error", "error_message": f"Firestore read failed: {exc}"}
        return _approval_result(existing)

    scenario = _load_scenario()
    requester = Person(name=scenario["requester"]["name"])
    providers = [Organization(name=spec["name"]) for spec in scenario["providers"]]
    provider_by_name = {provider.name: provider for provider in providers}

    contacts: dict[str, dict[str, str]] = {}
    contact_points: list[ContactPoint] = []
    behaviors: dict[str, dict[str, Any]] = {}
    for spec in scenario["providers"]:
        provider = provider_by_name[spec["name"]]
        contact = ContactPoint(
            owner_id=provider.id,
            channel=Channel(spec["channel"]),
            address=spec["contact"],
        )
        contact_points.append(contact)
        contacts[provider.id] = {
            "contact_point_id": contact.id,
            "channel": contact.channel.value,
        }
        behaviors[provider.id] = {
            "outcome": spec["mock_outcome"],
            "slots": list(spec.get("slots", [])),
            "note": spec.get("note", ""),
        }

    request = AppointmentRequest(
        requester_id=requester.id,
        purpose=scenario["request"]["purpose"],
        location=scenario["request"]["location"],
        candidate_provider_ids=[provider.id for provider in providers],
    )
    try:
        backend = _backend_name()
        run_id = new_id("run")
        store = _new_store(run_id, backend)
    except Exception as exc:
        return {"status": "error", "error_message": str(exc)}
    store.put("Person", requester.id, serialize(requester))
    for provider in providers:
        store.put("Organization", provider.id, serialize(provider))
    for contact in contact_points:
        store.put("ContactPoint", contact.id, serialize(contact))

    workflow = AppointmentWorkflow(
        request=request,
        provider_contacts=contacts,
        provider_service=MockRepairProviderService(behaviors),
        store=store,
    )
    proposal = None
    for provider in providers:
        proposal = workflow.try_provider(provider.id)
        if proposal is not None:
            break
    if proposal is None:
        return {"status": "error", "error_message": "No provider proposed a slot."}

    workflow.request_human_approval(proposal)
    snapshot = _snapshot(request, proposal, store, run_id, backend)
    if isinstance(store, FirestoreStateStore):
        try:
            store.save_snapshot(snapshot)
        except Exception as exc:
            return {"status": "error", "error_message": f"Firestore write failed: {exc}"}
    tool_context.state[STATE_KEY] = snapshot
    return _approval_result(snapshot)


def confirm_appointment(slot: str, tool_context: ToolContext) -> dict[str, Any]:
    """Confirm an explicitly approved slot using the existing workflow logic."""
    snapshot = tool_context.state.get(STATE_KEY)
    if not isinstance(snapshot, dict):
        return {"status": "error", "error_message": "No appointment workflow snapshot exists."}

    backend = snapshot.get("backend", "json")
    run_id = snapshot.get("run_id")
    if backend == "firestore":
        if not run_id:
            return {"status": "error", "error_message": "Firestore snapshot has no run_id."}
        try:
            persisted_store = _new_store(run_id, backend)
            persisted = persisted_store.load_snapshot()
        except Exception as exc:
            return {"status": "error", "error_message": f"Firestore read failed: {exc}"}
        if persisted is None:
            return {
                "status": "error",
                "error_message": f"No Firestore workflow exists for run_id {run_id}.",
            }
        snapshot = persisted

    state = snapshot.get("request_state")
    selected_slot = snapshot.get("selected_slot")
    if state == RequestState.CONFIRMED.value:
        if slot != selected_slot:
            return {
                "status": "error",
                "error_message": "The appointment is already confirmed for a different slot.",
            }
        appointments = snapshot["store_state"]["objects"].get("Appointment", {})
        appointment = appointments.get(snapshot.get("appointment_id"), {})
        return {
            "status": "success",
            "request_state": state,
            "appointment_id": snapshot.get("appointment_id"),
            "provider_id": appointment.get("provider_id"),
            "starts_at": appointment.get("starts_at"),
            "message": "The appointment was already confirmed for this slot.",
        }

    if state != RequestState.AWAITING_HUMAN_APPROVAL.value:
        return {
            "status": "error",
            "error_message": "The request is not awaiting human approval.",
        }
    if slot not in snapshot.get("available_slots", []):
        return {
            "status": "error",
            "error_message": "The approved slot is not in the saved provider proposal.",
        }

    try:
        store = _new_store(
            snapshot.get("run_id", run_id or new_id("run")),
            backend,
            snapshot["store_state"],
        )
    except Exception as exc:
        return {"status": "error", "error_message": str(exc)}
    objects = store.state["objects"]
    request_data = objects.get("AppointmentRequest", {}).get(snapshot.get("request_id"))
    proposal_data = objects.get("TimeProposal", {}).get(snapshot.get("proposal_id"))
    if not request_data or not proposal_data:
        return {
            "status": "error",
            "error_message": "The saved workflow snapshot is incomplete.",
        }

    request = _rehydrate_request(request_data)
    proposal = _rehydrate_proposal(proposal_data)
    workflow = AppointmentWorkflow(
        request=request,
        provider_contacts={},
        provider_service=MockRepairProviderService({}),
        store=store,
    )
    try:
        appointment = workflow.approve_and_confirm(proposal, slot)
    except (KeyError, TypeError, ValueError) as exc:
        return {"status": "error", "error_message": str(exc)}

    updated = _snapshot(
        request,
        proposal,
        store,
        snapshot.get("run_id", run_id),
        backend,
    )
    if isinstance(store, FirestoreStateStore):
        try:
            store.save_snapshot(updated)
        except Exception as exc:
            return {"status": "error", "error_message": f"Firestore write failed: {exc}"}
    tool_context.state[STATE_KEY] = updated
    return {
        "status": "success",
        "request_state": request.state.value,
        "appointment_id": appointment.id,
        "provider_id": appointment.provider_id,
        "starts_at": appointment.starts_at,
        "message": "The approved appointment was confirmed.",
    }
