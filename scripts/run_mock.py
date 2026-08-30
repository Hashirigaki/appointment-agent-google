import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from appointment_agent.mock_services import MockRepairProviderService
from appointment_agent.ontology import (
    AppointmentRequest,
    Channel,
    ContactPoint,
    Organization,
    Person,
    serialize,
)
from appointment_agent.state_store import JsonStateStore
from appointment_agent.workflow import AppointmentWorkflow


def main():
    scenario_path = ROOT / "data" / "scenario_ac_repair.json"
    scenario = json.loads(scenario_path.read_text(encoding="utf-8"))

    requester = Person(name=scenario["requester"]["name"])
    providers = [
        Organization(name=p["name"])
        for p in scenario["providers"]
    ]

    provider_by_name = {p.name: p for p in providers}

    contacts = {}
    contact_points = []
    provider_behaviors = {}

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
        provider_behaviors[provider.id] = {
            "outcome": spec["mock_outcome"],
            "slots": spec.get("slots", []),
            "note": spec.get("note", ""),
        }

    request = AppointmentRequest(
        requester_id=requester.id,
        purpose=scenario["request"]["purpose"],
        location=scenario["request"]["location"],
        candidate_provider_ids=[p.id for p in providers],
    )

    store = JsonStateStore(str(ROOT / "data" / "mock_run_output.json"))
    store.put("Person", requester.id, serialize(requester))
    for provider in providers:
        store.put("Organization", provider.id, serialize(provider))
    for contact_point in contact_points:
        store.put(
            "ContactPoint",
            contact_point.id,
            serialize(contact_point),
        )

    service = MockRepairProviderService(provider_behaviors)
    workflow = AppointmentWorkflow(
        request=request,
        provider_contacts=contacts,
        provider_service=service,
        store=store,
    )

    print("\n=== Appointment Agent mock v0.1.1 ===")
    print(f"Purpose: {request.purpose}")
    print(f"Request: {request.id}\n")

    proposal = None
    for provider in providers:
        proposal = workflow.try_provider(provider.id)
        if proposal is not None:
            break

    if proposal is None:
        raise RuntimeError("No provider returned a time proposal.")

    workflow.request_human_approval(proposal)

    # Mock user decision: choose the first proposed slot.
    approved_slot = proposal.slots[0]
    print(f"[HUMAN] approved slot: {approved_slot}")

    appointment = workflow.approve_and_confirm(proposal, approved_slot)
    store.flush()

    print("\n=== RESULT ===")
    print(f"Appointment: {appointment.id}")
    print(f"Provider:    {appointment.provider_id}")
    print(f"Starts at:   {appointment.starts_at}")
    print(f"State file:  {ROOT / 'data' / 'mock_run_output.json'}")


if __name__ == "__main__":
    main()
