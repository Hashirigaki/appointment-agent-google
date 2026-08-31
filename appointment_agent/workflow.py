from typing import Dict, List
from .ontology import (
    Appointment,
    AppointmentRequest,
    AttemptOutcome,
    Channel,
    ContactAttempt,
    EventCard,
    RequestState,
    TimeProposal,
    TransitionEvent,
    serialize,
)
from .mock_services import MockRepairProviderService
from .state_store import JsonStateStore


class AppointmentWorkflow:
    def __init__(
        self,
        request: AppointmentRequest,
        provider_contacts: Dict[str, dict],
        provider_service: MockRepairProviderService,
        store: JsonStateStore,
        run_id: str | None = None,
        requester_detail_id: str | None = None,
        provider_detail_ids: Dict[str, str] | None = None,
    ):
        self.request = request
        self.provider_contacts = provider_contacts
        self.provider_service = provider_service
        self.store = store
        self.proposals: List[TimeProposal] = []
        self.run_id = run_id
        self.requester_detail_id = requester_detail_id
        self.provider_detail_ids = provider_detail_ids or {}

        self.store.put("AppointmentRequest", request.id, serialize(request))

    def _semantic_event(self, event_type: str, user_id: str, detail_id: str | None):
        if not self.run_id or not detail_id:
            return
        self.store.append_semantic_event(
            serialize(
                EventCard(
                    run_id=self.run_id,
                    user_id=user_id,
                    detail_id=detail_id,
                    event_type=event_type,
                )
            )
        )

    def start_trajectory(self):
        """Record the two semantic events that begin a new appointment run."""
        self._semantic_event(
            "inbound_contact",
            self.request.requester_id,
            self.requester_detail_id,
        )
        self._semantic_event(
            "agent_processing",
            self.request.requester_id,
            self.requester_detail_id,
        )

    def _transition(self, to_state: RequestState, action: str, reason: str):
        event = TransitionEvent(
            request_id=self.request.id,
            from_state=self.request.state,
            to_state=to_state,
            action=action,
            reason=reason,
        )
        print(
            f"[STATE] {self.request.state.value:24s} -> "
            f"{to_state.value:24s} | {action} | {reason}"
        )
        self.request.state = to_state
        self.store.append_event(serialize(event))
        self.store.put("AppointmentRequest", self.request.id, serialize(self.request))

    def try_provider(self, provider_id: str):
        contact = self.provider_contacts[provider_id]
        provider_detail_id = self.provider_detail_ids.get(provider_id)

        self._semantic_event("outbound_contact", provider_id, provider_detail_id)

        self._transition(
            RequestState.CONTACTING,
            action="contact_provider",
            reason=f"Attempting provider {provider_id} via {contact['channel']}.",
        )

        response = self.provider_service.contact(provider_id, self.request.id)

        attempt = ContactAttempt(
            request_id=self.request.id,
            provider_id=provider_id,
            contact_point_id=contact["contact_point_id"],
            channel=Channel(contact["channel"]),
            outcome=response.outcome,
            note=response.note,
        )
        self.request.contact_attempt_ids.append(attempt.id)
        self.store.put("ContactAttempt", attempt.id, serialize(attempt))

        if response.outcome == AttemptOutcome.NO_RESPONSE:
            self._transition(
                RequestState.AWAITING_REPLY,
                action="record_no_response",
                reason=response.note or "Provider did not respond.",
            )
            self._transition(
                RequestState.RETRY_DUE,
                action="schedule_retry",
                reason="Another provider is available; retry is allowed.",
            )
            return None

        if response.outcome == AttemptOutcome.SLOTS_PROPOSED:
            self._semantic_event("reply", provider_id, provider_detail_id)
            proposal = TimeProposal(
                request_id=self.request.id,
                provider_id=provider_id,
                slots=response.slots,
            )
            self.proposals.append(proposal)
            self.request.proposal_ids.append(proposal.id)
            self.store.put("TimeProposal", proposal.id, serialize(proposal))
            self._transition(
                RequestState.TIME_PROPOSED,
                action="record_time_proposal",
                reason=f"Provider proposed {len(response.slots)} candidate slots.",
            )
            return proposal

        self._transition(
            RequestState.FAILED,
            action="provider_failed",
            reason=response.note or response.outcome.value,
        )
        return None

    def request_human_approval(self, proposal: TimeProposal):
        self._transition(
            RequestState.AWAITING_HUMAN_APPROVAL,
            action="ask_human",
            reason="A consequential time commitment requires user approval.",
        )

    def approve_and_confirm(self, proposal: TimeProposal, slot: str):
        if slot not in proposal.slots:
            raise ValueError("Approved slot must come from the provider proposal.")

        self.request.selected_slot = slot
        self.request.selected_provider_id = proposal.provider_id

        appointment = Appointment(
            request_id=self.request.id,
            requester_id=self.request.requester_id,
            provider_id=proposal.provider_id,
            starts_at=slot,
            purpose=self.request.purpose,
        )
        self.request.appointment_id = appointment.id
        self.store.put("Appointment", appointment.id, serialize(appointment))

        self._transition(
            RequestState.CONFIRMED,
            action="confirm_appointment",
            reason=f"Human approved {slot}; appointment created.",
        )
        return appointment
