from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4
from datetime import datetime, timezone


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:10]}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Channel(str, Enum):
    EMAIL = "email"
    PHONE = "phone"
    SNS = "sns"
    WEB = "web"
    FACE_TO_FACE = "face_to_face"
    AGENT = "agent"


class RequestState(str, Enum):
    REQUESTED = "requested"
    CONTACTING = "contacting"
    AWAITING_REPLY = "awaiting_reply"
    RETRY_DUE = "retry_due"
    TIME_PROPOSED = "time_proposed"
    AWAITING_HUMAN_APPROVAL = "awaiting_human_approval"
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


class AttemptOutcome(str, Enum):
    NO_RESPONSE = "no_response"
    REJECTED = "rejected"
    SLOTS_PROPOSED = "slots_proposed"
    CONFIRMED = "confirmed"
    ERROR = "error"


@dataclass
class Person:
    name: str
    id: str = field(default_factory=lambda: new_id("person"))


@dataclass
class Organization:
    name: str
    id: str = field(default_factory=lambda: new_id("org"))


@dataclass
class ContactPoint:
    owner_id: str
    channel: Channel
    address: str
    id: str = field(default_factory=lambda: new_id("contact"))


@dataclass
class TimeProposal:
    request_id: str
    provider_id: str
    slots: List[str]
    id: str = field(default_factory=lambda: new_id("proposal"))
    created_at: str = field(default_factory=now_iso)


@dataclass
class ContactAttempt:
    request_id: str
    provider_id: str
    contact_point_id: str
    channel: Channel
    outcome: AttemptOutcome
    id: str = field(default_factory=lambda: new_id("attempt"))
    created_at: str = field(default_factory=now_iso)
    note: Optional[str] = None


@dataclass
class Appointment:
    request_id: str
    requester_id: str
    provider_id: str
    starts_at: str
    purpose: str
    id: str = field(default_factory=lambda: new_id("appt"))
    status: str = "confirmed"


@dataclass
class AppointmentRequest:
    requester_id: str
    purpose: str
    location: str
    candidate_provider_ids: List[str]
    state: RequestState = RequestState.REQUESTED
    id: str = field(default_factory=lambda: new_id("request"))
    created_at: str = field(default_factory=now_iso)
    contact_attempt_ids: List[str] = field(default_factory=list)
    proposal_ids: List[str] = field(default_factory=list)
    selected_slot: Optional[str] = None
    selected_provider_id: Optional[str] = None
    appointment_id: Optional[str] = None


@dataclass
class TransitionEvent:
    request_id: str
    from_state: RequestState
    to_state: RequestState
    action: str
    reason: str
    id: str = field(default_factory=lambda: new_id("event"))
    created_at: str = field(default_factory=now_iso)


@dataclass(frozen=True)
class TrajectoryCard:
    """One workflow run; Event Cards are linked by run_id, not embedded here."""

    run_id: str


@dataclass(frozen=True)
class EventCard:
    """Upper-layer semantic event used to reconstruct a trajectory."""

    run_id: str
    user_id: str
    detail_id: str
    event_type: str
    event_id: str = field(default_factory=lambda: new_id("semantic_event"))
    start_time: str = field(default_factory=now_iso)


@dataclass
class DetailCard:
    """Current editable data for a person or organization referenced by Events."""

    user_id: str
    user_data: Dict[str, Any]
    detail_id: str = field(default_factory=lambda: new_id("detail"))


def serialize(obj):
    data = asdict(obj)
    for key, value in list(data.items()):
        if isinstance(value, Enum):
            data[key] = value.value
        elif isinstance(value, list):
            data[key] = [v.value if isinstance(v, Enum) else v for v in value]
    return data
