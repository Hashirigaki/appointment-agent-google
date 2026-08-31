import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Iterable

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from google.cloud.firestore_v1.services.firestore import FirestoreClient


class FirestoreRestClient(firestore.Client):
    """High-level Firestore client using the library's REST transport."""

    @property
    def _firestore_api(self):
        if self._firestore_api_internal is None:
            self._firestore_api_internal = FirestoreClient(
                credentials=self._credentials,
                transport="rest",
                client_options=self._client_options,
                client_info=self._client_info,
            )
        return self._firestore_api_internal


def create_firestore_client(project: str, database: str) -> firestore.Client:
    return FirestoreRestClient(project=project, database=database)


V02_EVENT_FIELDS = {
    "event_id",
    "run_id",
    "user_id",
    "detail_id",
    "event_type",
    "start_time",
}


def empty_state() -> Dict[str, Any]:
    return {
        "objects": {},
        "events": [],
        "trajectories": {},
        "semantic_events": {},
        "details": {},
    }


def normalize_state(state: Dict[str, Any]) -> Dict[str, Any]:
    """Make v0.1 snapshots readable without rewriting their existing records."""
    state.setdefault("objects", {})
    state.setdefault("events", [])
    state.setdefault("trajectories", {})
    state.setdefault("semantic_events", {})
    state.setdefault("details", {})
    return state


class TrajectoryStateMixin:
    state: Dict[str, Any]

    def put_trajectory(self, data: dict) -> None:
        run_id = data.get("run_id")
        if not run_id:
            raise ValueError("Trajectory Card requires run_id.")
        normalize_state(self.state)["trajectories"][run_id] = deepcopy(data)

    def put_detail(self, data: dict) -> None:
        detail_id = data.get("detail_id")
        if not detail_id or not data.get("user_id"):
            raise ValueError("Detail Card requires detail_id and user_id.")
        if "user_data" not in data:
            raise ValueError("Detail Card requires user_data.")
        normalize_state(self.state)["details"][detail_id] = deepcopy(data)

    def update_detail(self, detail_id: str, user_data: dict) -> dict:
        details = normalize_state(self.state)["details"]
        if detail_id not in details:
            raise KeyError(f"Unknown detail_id: {detail_id}")
        details[detail_id]["user_data"] = deepcopy(user_data)
        return deepcopy(details[detail_id])

    def append_semantic_event(self, data: dict) -> None:
        missing = V02_EVENT_FIELDS.difference(data)
        if missing:
            raise ValueError(
                "Event Card is missing required fields: " + ", ".join(sorted(missing))
            )
        event_id = data["event_id"]
        events = normalize_state(self.state)["semantic_events"]
        if event_id in events:
            if events[event_id] != data:
                raise ValueError(f"Event Card {event_id} is append-only.")
            return
        events[event_id] = deepcopy(data)

    def get_events_for_run(self, run_id: str) -> list[dict]:
        events: Iterable[dict] = normalize_state(self.state)["semantic_events"].values()
        return sorted(
            (deepcopy(event) for event in events if event["run_id"] == run_id),
            key=lambda event: (event["start_time"], event["event_id"]),
        )

    def get_trajectories_for_user(self, user_id: str) -> list[dict]:
        events = [
            deepcopy(event)
            for event in normalize_state(self.state)["semantic_events"].values()
            if event["user_id"] == user_id
        ]
        run_ids = sorted({event["run_id"] for event in events})
        trajectories = normalize_state(self.state)["trajectories"]
        return [
            {
                "trajectory": deepcopy(trajectories[run_id]),
                "events": self.get_events_for_run(run_id),
            }
            for run_id in run_ids
            if run_id in trajectories
        ]


class JsonStateStore(TrajectoryStateMixin):
    def __init__(self, path: str):
        self.path = Path(path)
        self.state: Dict[str, Any] = empty_state()

    def put(self, object_type: str, object_id: str, data: dict):
        self.state["objects"].setdefault(object_type, {})
        self.state["objects"][object_type][object_id] = data

    def append_event(self, data: dict):
        self.state["events"].append(data)

    def flush(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


class FirestoreStateStore(TrajectoryStateMixin):
    """Persist the workflow snapshot plus separate v0.2 card collections."""

    def __init__(
        self,
        run_id: str,
        project: str,
        database: str,
        collection: str,
        trajectory_collection: str = "trajectories",
        event_collection: str = "events",
        detail_collection: str = "details",
    ):
        self.run_id = run_id
        self.client = create_firestore_client(project=project, database=database)
        self.document = self.client.collection(collection).document(run_id)
        self.trajectory_collection = trajectory_collection
        self.event_collection = event_collection
        self.detail_collection = detail_collection
        self.state: Dict[str, Any] = empty_state()

    def put(self, object_type: str, object_id: str, data: dict):
        self.state["objects"].setdefault(object_type, {})
        self.state["objects"][object_type][object_id] = data

    def append_event(self, data: dict):
        self.state["events"].append(data)

    def save_snapshot(self, snapshot: dict):
        snapshot = deepcopy(snapshot)
        snapshot["store_state"] = normalize_state(snapshot["store_state"])
        self.state = deepcopy(snapshot["store_state"])
        batch = self.client.batch()
        batch.set(self.document, snapshot)
        for run_id, trajectory in self.state["trajectories"].items():
            batch.set(
                self.client.collection(self.trajectory_collection).document(run_id),
                trajectory,
            )
        for event_id, event in self.state["semantic_events"].items():
            batch.set(
                self.client.collection(self.event_collection).document(event_id),
                event,
            )
        for detail_id, detail in self.state["details"].items():
            batch.set(
                self.client.collection(self.detail_collection).document(detail_id),
                detail,
            )
        batch.commit()

    def load_snapshot(self) -> dict | None:
        document = self.document.get()
        if not document.exists:
            return None
        snapshot = document.to_dict()
        if isinstance(snapshot.get("store_state"), dict):
            snapshot["store_state"] = normalize_state(snapshot["store_state"])
        return snapshot

    def get_events_for_run(self, run_id: str) -> list[dict]:
        documents = (
            self.client.collection(self.event_collection)
            .where(filter=FieldFilter("run_id", "==", run_id))
            .stream()
        )
        return sorted(
            (document.to_dict() for document in documents),
            key=lambda event: (event["start_time"], event["event_id"]),
        )

    def get_trajectories_for_user(self, user_id: str) -> list[dict]:
        documents = (
            self.client.collection(self.event_collection)
            .where(filter=FieldFilter("user_id", "==", user_id))
            .stream()
        )
        run_ids = sorted({document.to_dict()["run_id"] for document in documents})
        results = []
        for run_id in run_ids:
            trajectory = (
                self.client.collection(self.trajectory_collection)
                .document(run_id)
                .get()
            )
            if trajectory.exists:
                results.append(
                    {
                        "trajectory": trajectory.to_dict(),
                        "events": self.get_events_for_run(run_id),
                    }
                )
        return results

    def update_detail(self, detail_id: str, user_data: dict) -> dict:
        detail_ref = self.client.collection(self.detail_collection).document(detail_id)
        document = detail_ref.get()
        if not document.exists:
            raise KeyError(f"Unknown detail_id: {detail_id}")
        detail = document.to_dict()
        detail["user_data"] = deepcopy(user_data)
        batch = self.client.batch()
        batch.set(detail_ref, detail)
        batch.set(
            self.document,
            {"store_state": {"details": {detail_id: detail}}},
            merge=True,
        )
        batch.commit()
        normalize_state(self.state)["details"][detail_id] = deepcopy(detail)
        return deepcopy(detail)

    def flush(self):
        """Compatibility method; workflow snapshots are saved atomically."""
        self.save_snapshot({"run_id": self.run_id, "store_state": self.state})
