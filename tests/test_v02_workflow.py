import os
import unittest
from unittest.mock import patch

from appointment_agent.adk_tools import (
    STATE_KEY,
    confirm_appointment,
    run_appointment_to_approval,
)


EXPECTED_FLOW = [
    "requested",
    "contacting",
    "awaiting_reply",
    "retry_due",
    "contacting",
    "time_proposed",
    "awaiting_human_approval",
    "confirmed",
]


class FakeToolContext:
    def __init__(self):
        self.state = {}


class V02WorkflowTest(unittest.TestCase):
    def test_existing_two_turn_flow_and_v02_trajectory_both_complete(self):
        context = FakeToolContext()
        with patch.dict(os.environ, {"APPOINTMENT_STATE_BACKEND": "json"}):
            first = run_appointment_to_approval(context)
            self.assertEqual(first["request_state"], "awaiting_human_approval")
            self.assertTrue(first["requires_human_approval"])

            approved_slot = first["available_slots"][0]
            final = confirm_appointment(approved_slot, context)

        self.assertEqual(final["request_state"], "confirmed")
        snapshot = context.state[STATE_KEY]
        transitions = snapshot["store_state"]["events"]
        flow = [transitions[0]["from_state"]] + [
            event["to_state"] for event in transitions
        ]
        self.assertEqual(flow, EXPECTED_FLOW)

        run_id = snapshot["run_id"]
        trajectory = snapshot["store_state"]["trajectories"][run_id]
        semantic_events = snapshot["store_state"]["semantic_events"].values()
        self.assertEqual(trajectory, {"run_id": run_id})
        self.assertGreaterEqual(len(snapshot["store_state"]["semantic_events"]), 4)
        self.assertEqual(
            [event["event_type"] for event in semantic_events],
            [
                "inbound_contact",
                "agent_processing",
                "outbound_contact",
                "outbound_contact",
                "reply",
            ],
        )
        self.assertTrue(all(event["run_id"] == run_id for event in semantic_events))
        self.assertTrue(all("user_data" not in event for event in semantic_events))


if __name__ == "__main__":
    unittest.main()
