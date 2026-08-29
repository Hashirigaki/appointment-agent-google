import json
from pathlib import Path
from typing import Any, Dict


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
