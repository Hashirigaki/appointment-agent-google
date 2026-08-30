"""
Google ADK scaffold.

This file is intentionally thin in v0.1.1. The deterministic workflow in
workflow.py establishes the domain semantics first; ADK is the orchestration
layer on top of that domain model.
"""

import os
from google.adk.agents import Agent

MODEL_NAME = os.getenv("MODEL_NAME", "gemini-3.5-flash")


def describe_ontology() -> dict:
    """Return the canonical object types the agent is allowed to reason about."""
    return {
        "object_types": [
            "Person",
            "Organization",
            "ContactPoint",
            "AppointmentRequest",
            "ContactAttempt",
            "TimeProposal",
            "Appointment",
            "TransitionEvent",
        ],
        "principle": (
            "Do not invent channel-specific AppointmentRequest types. "
            "Represent contact methods as ContactPoint / ContactAttempt."
        ),
    }


def explain_human_boundary() -> dict:
    """Return the v0.1.1 approval policy."""
    return {
        "requires_human_approval": [
            "committing the requester to a proposed appointment time",
        ],
        "agent_may_do_without_approval": [
            "create request state",
            "contact a provider",
            "record no-response",
            "retry another provider",
            "record provider-proposed time slots",
        ],
    }


root_agent = Agent(
    name="appointment_agent",
    model=MODEL_NAME,
    description=(
        "Ontology-first agent for completing multi-step appointment workflows."
    ),
    instruction=(
        "You manage appointment workflows using the canonical ontology. "
        "Treat entities, observations, and actions as separate concepts. "
        "Do not create channel-specific request types. "
        "You may retry providers after no response. "
        "Before committing a human to a time slot, require human approval. "
        "Use tools to inspect the ontology and approval boundary."
    ),
    tools=[describe_ontology, explain_human_boundary],
)
