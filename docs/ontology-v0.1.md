# Appointment Ontology v0.1

## Design rule

Model the real-world appointment domain, not the transport system.

Bad:

```text
EmailAppointmentRequest
PhoneAppointmentRequest
SNSAppointmentRequest
```

Preferred:

```text
AppointmentRequest
  -> ContactAttempt
       -> ContactPoint(channel=email|phone|sns|...)
```

## Object types

### Person
A human actor with stable identity.

### Organization
A provider, company, property manager, clinic, etc.

### ContactPoint
A way to reach a Person or Organization.

Properties:
- owner_id
- channel
- address

### AppointmentRequest
The durable intention to create an appointment.

Properties:
- requester
- purpose
- location
- candidate providers
- state

### ContactAttempt
An event/observation, not the identity of the provider or request.

Properties:
- request
- provider
- contact point
- channel
- outcome
- timestamp

### TimeProposal
A provider-originated set of candidate appointment slots.

### Appointment
The confirmed real-world commitment.

### TransitionEvent
Audit record explaining how and why request state changed.

## State machine

```text
REQUESTED
  -> CONTACTING
  -> AWAITING_REPLY
  -> RETRY_DUE
  -> CONTACTING
  -> TIME_PROPOSED
  -> AWAITING_HUMAN_APPROVAL
  -> CONFIRMED
  -> COMPLETED
```

Failure branches exist from contact / retry stages.

## Human boundary v0.1

The agent may autonomously:
- normalize request data
- select a provider candidate
- initiate a contact attempt
- record an unsuccessful attempt
- retry another provider
- receive and record proposed slots

The agent must ask a human before:
- committing the requester to a specific appointment time

This boundary is deliberately explicit so later versions can benchmark ask placement.
