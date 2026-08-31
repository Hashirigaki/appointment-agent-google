# Devpost Submission Draft

## Project name

Appointment Agent — Ontology-First Scheduling with Human Approval

## Tagline

A Google ADK agent that retries appointment outreach, preserves an auditable
workflow, and asks a human before making the commitment.

## Inspiration

Scheduling is a useful test of real agent behavior because success requires
more than generating text. An agent must preserve identity, remember contact
attempts, react to no response, handle provider-proposed times, and know when
autonomy should stop. We wanted to demonstrate that workflow clearly before
connecting a real phone or email provider.

## What it does

Appointment Agent runs a deterministic air-conditioner repair scenario. The
first mock provider does not respond, so the workflow records the attempt and
retries. The second provider returns two slots. Gemini, orchestrated through
Google ADK, calls `run_appointment_to_approval`, presents those slots, and stops
at `awaiting_human_approval`. Only after the user approves an exact proposed
slot does ADK call `confirm_appointment`. The existing domain workflow creates
the appointment and transitions to `confirmed`.

Every domain object and transition is recorded. In the deployed version, the
canonical snapshot is stored in Firestore under a unique `run_id`, so it does
not rely only on process memory. Version 0.2 also writes a separate trajectory,
append-only semantic events, and editable detail cards linked by stable IDs.

## How we built it

We began with an ontology that separates people, providers, contact points,
requests, attempts, proposals, appointments, and transition events. A small
state machine implements the workflow independently from the LLM. Google ADK
2.8.0 exposes that workflow through two function tools. Gemini 3.5 Flash chooses
the appropriate tool from the conversation while the deterministic Python code
enforces valid transitions and slot selection.

The private API is deployed to Cloud Run in `asia-northeast1` with a dedicated
runtime identity. Gemini runs through Vertex AI with model location `global`.
Firestore Native mode in `asia-northeast1` stores the canonical workflow
snapshot and the linked v0.2 trajectory, event, and detail cards. Cloud Run
remains authenticated-only; there is no public UI.

## Architecture

1. The user asks the ADK agent to arrange the mock repair appointment.
2. Gemini calls `run_appointment_to_approval`.
3. The deterministic workflow records no response, retries, and stores a
   two-slot proposal in Firestore.
4. The agent presents the slots and stops.
5. The user approves one exact slot in a second turn.
6. Gemini calls `confirm_appointment`.
7. The domain workflow confirms the appointment and updates the same Firestore
   run to `confirmed`.

## Challenges

The main design challenge was preventing the LLM orchestration layer from
becoming the source of domain truth. We solved this by keeping state transitions
and confirmation rules in deterministic classes, then rehydrating those classes
from a JSON-serializable snapshot. Another challenge was separating three
locations correctly: Gemini uses `global`, while Cloud Run and Firestore use
`asia-northeast1`.

We also treated security boundaries as product behavior: the agent cannot
confirm in the proposal turn, the Cloud Run service is private, and credentials
are excluded from source and build context.

## Accomplishments

- A complete retry-to-confirmation workflow with an explicit human boundary.
- Idempotent ADK tools backed by existing deterministic domain logic.
- Canonical Firestore persistence keyed by `run_id`.
- Linked trajectory, semantic event, and detail cards without recursively
  embedding editable detail data in event history.
- Authenticated private Cloud Run deployment with a least-privilege runtime.
- Automated smoke tests for tool order, state transitions, IDs, slot selection,
  Firestore integrity, and dangling references.

## What we learned

Useful agent systems benefit from separating ontology, deterministic policy,
LLM orchestration, persistence, and transport. Human approval is easiest to
trust when it is a visible state transition rather than a prompt convention.
We also learned that a reproducible offline demo is valuable even when the
production path uses managed cloud services.

## What's next

Future work could add a durable ADK session service, real provider adapters,
notifications, and additional scenarios. Those integrations should reuse the
same ontology and approval boundary rather than introducing channel-specific
request types.

## Transparent mock disclosure

The repair providers are deterministic simulations. No real phone call, email,
or booking occurs. Gemini, Google ADK, Cloud Run, Vertex AI, and Firestore are
used in live integration checks; only the external provider is mocked.
