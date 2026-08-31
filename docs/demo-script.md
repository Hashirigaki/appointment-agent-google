# Four-Minute Demo Script and Shot List

Target length: 3:30–3:50. Spoken language: English.

## 0:00–0:30 — Problem

**Shot:** Title slide, then the workflow states in the README.

**Narration:**

“Scheduling is not just a chat response. An agent must track who it contacted,
what happened, when to retry, which times came from the provider, and when to
stop for human approval. Appointment Agent demonstrates that complete workflow
with an ontology-first design.”

## 0:30–1:05 — Architecture

**Shot:** README Mermaid diagram and repository map.

**Narration:**

“Gemini 3.5 Flash uses Google ADK to select two tools, but the language model is
not the workflow engine. Deterministic Python domain classes enforce the state
machine. Cloud Run hosts a private authenticated API, and Firestore stores the
canonical snapshot by run ID. The provider itself is a transparent deterministic
mock.”

**On screen:** Briefly highlight `agent.py`, `workflow.py`, `adk_tools.py`, and
`state_store.py` without scrolling through implementation details.

## 1:05–1:50 — Turn 1

**Shot:** Terminal running the authenticated Cloud Run smoke or an ADK client.

**User prompt:**

```text
Use the mock AC repair scenario to arrange an appointment. Stop and ask me before confirming any time.
```

**Narration:**

“On turn one, Gemini calls `run_appointment_to_approval`. The first provider does
not respond, so the workflow records that attempt and retries. The second
provider proposes two slots.”

**Proof to show:** Tool name, the two exact slots, and the transition sequence
through `time_proposed`.

## 1:50–2:20 — Human approval boundary

**Shot:** The final Turn 1 response and session snapshot.

**Narration:**

“The agent does not confirm automatically. It stops in
`awaiting_human_approval`, presents only provider-originated slots, and asks the
user to choose. This boundary is enforced by both the ADK instruction and the
deterministic workflow.”

**Proof to show:** `request_state: awaiting_human_approval`, two available slots,
and no appointment ID.

## 2:20–2:55 — Turn 2

**User prompt:**

```text
I approve <EXACT_FIRST_PROPOSED_SLOT>. Confirm it.
```

**Narration:**

“On a separate turn, the user approves one exact proposal string. Gemini calls
`confirm_appointment`. The tool reloads the canonical run, rehydrates the domain
objects, and uses the existing confirmation method rather than duplicating
business logic.”

**Proof to show:** `confirm_appointment`, `selected_slot`, `appointment_id`, and
`request_state: confirmed`.

## 2:55–3:25 — Firestore confirmed state

**Shot:** Firestore console document with sensitive project identifiers cropped
or blurred.

**Narration:**

“The same run ID is now confirmed in Firestore. The canonical document contains
the request, proposal, appointment, and ordered state transitions. Version 0.2
also stores one linked trajectory, five semantic events, and three detail cards.
The smoke test checks that every run and detail reference resolves.”

**Proof to show:** `run_id`, `request_state`, `selected_slot`, `appointment_id`,
the trajectory, event/detail counts, and the final transition event. Do not show
contact addresses or detail payloads.

## 3:25–3:50 — Google Cloud proof and close

**Shot:** Cloud Run service overview showing the service name, private access,
region, healthy revision, and dedicated runtime identity. Hide project ID and
service account email. Optionally show the final PASS output.

**Narration:**

“The API runs privately on Cloud Run in Tokyo, uses Vertex AI for Gemini, and
persists canonical workflow state in Firestore. The key result is not just a
booking—it is a traceable agent that knows when it may act and when it must ask.”

## Recording fallback

If local security software blocks direct authenticated TLS on recording day,
record the deterministic path without changing the application:

```powershell
.\scripts\run_demo.ps1
```

Clearly label this as the offline deterministic replay. Add previously captured
Cloud Run and Firestore proof shots; do not imply the mock provider is real.
