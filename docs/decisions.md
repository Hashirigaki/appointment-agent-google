# Architecture Decisions

## ADR-001 — AppointmentRequest is channel-agnostic

**Decision:** Do not define PhoneAppointmentRequest or EmailAppointmentRequest.

**Reason:** The user's goal is the same appointment regardless of transport channel. Channel belongs to contact/interaction events.

## ADR-002 — Contact attempts are first-class objects

**Decision:** A failed call or unanswered email is stored as a ContactAttempt.

**Reason:** Failure history matters for retry strategy, auditability, and later evaluation.

## ADR-003 — Human approval is an action boundary

**Decision:** The agent can obtain proposals autonomously but cannot commit the requester to a time without approval in v0.1.

**Reason:** This makes the human/agent decision boundary observable and benchmarkable.

## ADR-004 — External provider is mocked first

**Decision:** Use a deterministic provider simulator before integrating phone/email APIs.

**Reason:** It allows the ontology and workflow semantics to be tested independently of transport failures and credentials.
