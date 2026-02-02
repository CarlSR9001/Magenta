"""Telemetry utilities for run tracing."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import List

from .models import TelemetryEvent


class TelemetryStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: TelemetryEvent) -> None:
        payload = asdict(event)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")

    def read_all(self) -> List[TelemetryEvent]:
        if not self.path.exists():
            return []
        events: List[TelemetryEvent] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            events.append(TelemetryEvent(**data))
        return events
