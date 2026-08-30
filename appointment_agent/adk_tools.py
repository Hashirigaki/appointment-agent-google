"""ADK function tools for the deterministic appointment workflow."""

from copy import deepcopy
import json
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
    serialize,
)
from .state_store import JsonStateStore
from .workflow import AppointmentWorkflow


STATE_KEY = "appointment_workflow"
ROOT = Path(__file__).resolve().parents[1]


def _load_scenario() -> dict[str, Any]:
    path = ROOT / "data" / "scenario_ac_repair.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _new_store(state: dict[str, Any] | None = None) -> JsonStateStore:
    # The ADK session snapshot is authoritative; this path is never flushed.
    store = JsonStateStore(str(ROOT / "data" / "adk_workflow_unused.json"))
    if state is not None:
        store.state = deepcopy(state)
    return store


def _snapshot(
    request: AppointmentRequest,
    proposal: TimeProposal,
    store: JsonStateStore,
) -> dict[str, Any]:
    return {
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
    store = _new_store()
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
    snapshot = _snapshot(request, proposal, store)
    tool_context.state[STATE_KEY] = snapshot
    return _approval_result(snapshot)


def confirm_appointment(slot: str, tool_context: ToolContext) -> dict[str, Any]:
    """Confirm an explicitly approved slot using the existing workflow logic."""
    snapshot = tool_context.state.get(STATE_KEY)
    if not isinstance(snapshot, dict):
        return {"status": "error", "error_message": "No appointment workflow snapshot exists."}

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

    store = _new_store(snapshot["store_state"])
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

    updated = _snapshot(request, proposal, store)
    tool_context.state[STATE_KEY] = updated
    return {
        "status": "success",
        "request_state": request.state.value,
        "appointment_id": appointment.id,
        "provider_id": appointment.provider_id,
        "starts_at": appointment.starts_at,
        "message": "The approved appointment was confirmed.",
    }
