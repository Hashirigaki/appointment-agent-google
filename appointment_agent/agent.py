"""
Google ADK scaffold.

This file is intentionally thin in v0.1.1. The deterministic workflow in
workflow.py establishes the domain semantics first; ADK is the orchestration
layer on top of that domain model.
"""

import os
from google.adk.agents import Agent

from .adk_tools import confirm_appointment, run_appointment_to_approval

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
            "TrajectoryCard",
            "EventCard",
            "DetailCard",
        ],
        "principle": (
            "Do not invent channel-specific AppointmentRequest types. "
            "Represent contact methods as ContactPoint / ContactAttempt. "
            "Link TrajectoryCard, EventCard, and DetailCard by stable IDs."
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
        "For an appointment execution request, call run_appointment_to_approval. "
        "After receiving a provider proposal, present its slots to the user and stop "
        "in awaiting_human_approval; never confirm in the same turn. "
        "Do not call confirm_appointment until the user explicitly approves a slot. "
        "When approved, pass only the exact slot string from the proposal to "
        "confirm_appointment. Use the other tools to inspect the ontology and "
        "approval boundary."
    ),
    tools=[
        describe_ontology,
        explain_human_boundary,
        run_appointment_to_approval,
        confirm_appointment,
    ],
)
