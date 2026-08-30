import json
from pathlib import Path
from typing import Any, Dict

from google.cloud import firestore
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


class JsonStateStore:
    def __init__(self, path: str):
        self.path = Path(path)
        self.state: Dict[str, Any] = {
            "objects": {},
            "events": [],
        }

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


class FirestoreStateStore:
    """Persist one complete workflow snapshot in one Firestore document."""

    def __init__(
        self,
        run_id: str,
        project: str,
        database: str,
        collection: str,
    ):
        self.run_id = run_id
        self.client = create_firestore_client(project=project, database=database)
        self.document = self.client.collection(collection).document(run_id)
        self.state: Dict[str, Any] = {"objects": {}, "events": []}

    def put(self, object_type: str, object_id: str, data: dict):
        self.state["objects"].setdefault(object_type, {})
        self.state["objects"][object_type][object_id] = data

    def append_event(self, data: dict):
        self.state["events"].append(data)

    def save_snapshot(self, snapshot: dict):
        self.document.set(snapshot)

    def load_snapshot(self) -> dict | None:
        document = self.document.get()
        return document.to_dict() if document.exists else None

    def flush(self):
        """Compatibility method; workflow snapshots are saved atomically."""
        self.document.set(
            {"run_id": self.run_id, "store_state": self.state},
            merge=True,
        )
