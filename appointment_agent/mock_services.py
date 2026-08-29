from dataclasses import dataclass
from typing import Dict, List
from .ontology import AttemptOutcome


@dataclass
class MockProviderResponse:
    outcome: AttemptOutcome
    slots: List[str]
    note: str


class MockRepairProviderService:
    """
    Deterministic stand-in for a real third-party integration.

    Behavior is driven by provider scenario configuration:
    - no_response
    - slots_proposed
    - rejected
    """

    def __init__(self, provider_behaviors: Dict[str, dict]):
        self.provider_behaviors = provider_behaviors

    def contact(self, provider_id: str, request_id: str) -> MockProviderResponse:
        behavior = self.provider_behaviors[provider_id]
        outcome = AttemptOutcome(behavior["outcome"])
        return MockProviderResponse(
            outcome=outcome,
            slots=behavior.get("slots", []),
            note=behavior.get("note", ""),
        )
