from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from appointment_agent.ontology import DetailCard, EventCard, TrajectoryCard, serialize
from appointment_agent.state_store import (
    FirestoreStateStore,
    JsonStateStore,
    V02_EVENT_FIELDS,
    empty_state,
)


class FakeDocumentReference:
    def __init__(self, path):
        self.path = path


class FakeCollection:
    def __init__(self, name):
        self.name = name

    def document(self, document_id):
        return FakeDocumentReference(f"{self.name}/{document_id}")


class FakeBatch:
    def __init__(self):
        self.writes = []
        self.committed = False

    def set(self, reference, data, **kwargs):
        self.writes.append((reference.path, deepcopy(data), kwargs))

    def commit(self):
        self.committed = True


class FakeFirestoreClient:
    def __init__(self):
        self.last_batch = None

    def collection(self, name):
        return FakeCollection(name)

    def batch(self):
        self.last_batch = FakeBatch()
        return self.last_batch


class TrajectoryStateStoreTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = JsonStateStore(
            str(Path(self.temporary_directory.name) / "state.json")
        )
        self.run_id = "run_test"
        self.user_id = "person_test"
        self.detail = DetailCard(
            detail_id="detail_test",
            user_id=self.user_id,
            user_data={"name": "Before"},
        )
        self.store.put_trajectory(serialize(TrajectoryCard(run_id=self.run_id)))
        self.store.put_detail(serialize(self.detail))

    def tearDown(self):
        self.temporary_directory.cleanup()

    def append_event(self, event_id: str, event_type: str, start_time: str) -> dict:
        event = EventCard(
            event_id=event_id,
            run_id=self.run_id,
            user_id=self.user_id,
            detail_id=self.detail.detail_id,
            event_type=event_type,
            start_time=start_time,
        )
        data = serialize(event)
        self.store.append_semantic_event(data)
        return data

    def test_forward_and_reverse_queries_use_ids_and_distinct_run_ids(self):
        later = self.append_event(
            "event_2", "agent_processing", "2026-08-31T00:00:02+00:00"
        )
        earlier = self.append_event(
            "event_1", "inbound_contact", "2026-08-31T00:00:01+00:00"
        )

        events = self.store.get_events_for_run(self.run_id)
        self.assertEqual([event["event_id"] for event in events], ["event_1", "event_2"])
        self.assertEqual(set(events[0]), V02_EVENT_FIELDS)
        self.assertNotIn("user_data", events[0])
        self.assertEqual(events, [earlier, later])

        trajectories = self.store.get_trajectories_for_user(self.user_id)
        self.assertEqual(len(trajectories), 1)
        self.assertEqual(trajectories[0]["trajectory"], {"run_id": self.run_id})
        self.assertEqual(trajectories[0]["events"], events)

    def test_detail_edit_does_not_rewrite_event_history(self):
        self.append_event(
            "event_1", "inbound_contact", "2026-08-31T00:00:01+00:00"
        )
        before = deepcopy(self.store.state["semantic_events"])

        updated = self.store.update_detail(
            self.detail.detail_id,
            {"name": "After", "preferred_channel": "email"},
        )

        self.assertEqual(updated["user_data"]["name"], "After")
        self.assertEqual(self.store.state["semantic_events"], before)

    def test_event_records_are_append_only(self):
        original = self.append_event(
            "event_1", "inbound_contact", "2026-08-31T00:00:01+00:00"
        )
        self.store.append_semantic_event(deepcopy(original))
        changed = deepcopy(original)
        changed["event_type"] = "reply"

        with self.assertRaisesRegex(ValueError, "append-only"):
            self.store.append_semantic_event(changed)

    def test_firestore_snapshot_writes_separate_card_collections(self):
        event = self.append_event(
            "event_1", "inbound_contact", "2026-08-31T00:00:01+00:00"
        )
        client = FakeFirestoreClient()
        firestore_store = FirestoreStateStore.__new__(FirestoreStateStore)
        firestore_store.run_id = self.run_id
        firestore_store.client = client
        firestore_store.document = FakeDocumentReference(
            f"appointment_workflow_runs/{self.run_id}"
        )
        firestore_store.trajectory_collection = "trajectories"
        firestore_store.event_collection = "events"
        firestore_store.detail_collection = "details"
        firestore_store.state = empty_state()

        firestore_store.save_snapshot(
            {"run_id": self.run_id, "store_state": deepcopy(self.store.state)}
        )

        self.assertTrue(client.last_batch.committed)
        paths = {path for path, _, _ in client.last_batch.writes}
        self.assertIn(f"appointment_workflow_runs/{self.run_id}", paths)
        self.assertIn(f"trajectories/{self.run_id}", paths)
        self.assertIn(f"events/{event['event_id']}", paths)
        self.assertIn(f"details/{self.detail.detail_id}", paths)


if __name__ == "__main__":
    unittest.main()
