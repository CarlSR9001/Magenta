"""Filesystem-backed outbox for reversible drafts."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from .models import Draft, DraftType


class OutboxStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _draft_path(self, draft_id: str) -> Path:
        return self.root / f"{draft_id}.json"

    def create(self, draft: Draft) -> Draft:
        if not draft.id:
            draft.id = uuid.uuid4().hex[:12]
        self._write(draft)
        return draft

    def update(self, draft_id: str, edits: Dict) -> Draft:
        draft = self.get(draft_id)
        if draft is None:
            raise ValueError(f"Draft not found: {draft_id}")
        for key, value in edits.items():
            setattr(draft, key, value)
        draft.updated_at = datetime.now(timezone.utc).isoformat()
        self._write(draft)
        return draft

    def mark_aborted(self, draft_id: str, reason: str) -> Draft:
        draft = self.get(draft_id)
        metadata = (draft.metadata if draft else {}) or {}
        metadata = {**metadata, "abort_reason": reason}
        return self.update(draft_id, {"status": "aborted", "metadata": metadata})

    def mark_committed(self, draft_id: str, external_uri: Optional[str]) -> Draft:
        draft = self.get(draft_id)
        metadata = (draft.metadata if draft else {}) or {}
        if external_uri:
            metadata["commit_uri"] = external_uri
        return self.update(draft_id, {"status": "committed", "metadata": metadata})

    def mark_queued(self, draft_id: str, reason: str) -> Draft:
        draft = self.get(draft_id)
        metadata = (draft.metadata if draft else {}) or {}
        metadata["queue_reason"] = reason
        return self.update(draft_id, {"status": "queued", "metadata": metadata})

    def get(self, draft_id: str) -> Optional[Draft]:
        path = self._draft_path(draft_id)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return Draft(
            id=data["id"],
            type=DraftType(data["type"]),
            target_uri=data.get("target_uri"),
            text=data.get("text"),
            intent=data.get("intent", ""),
            constraints=data.get("constraints", []),
            confidence=data.get("confidence", 0.0),
            salience=data.get("salience", 0.0),
            salience_factors=data.get("salience_factors", {}),
            risk_flags=data.get("risk_flags", []),
            abort_if=data.get("abort_if", []),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            status=data.get("status", "draft"),
        )

    def _write(self, draft: Draft) -> None:
        payload = asdict(draft)
        payload["type"] = draft.type.value
        self._draft_path(draft.id).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def list_ids(self) -> list[str]:
        return [p.stem for p in self.root.glob("*.json")]

    def list_by_status(self, status: str) -> list[Draft]:
        drafts: list[Draft] = []
        for draft_id in self.list_ids():
            draft = self.get(draft_id)
            if draft and draft.status == status:
                drafts.append(draft)
        return drafts

    def purge_stale_drafts(self, max_age_hours: int = 24) -> int:
        """Purge drafts with status 'aborted' or 'error' older than max_age_hours.

        Args:
            max_age_hours: Maximum age in hours before a stale draft is purged.

        Returns:
            Count of purged drafts.
        """
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=max_age_hours)
        purged_count = 0

        for draft_id in self.list_ids():
            draft = self.get(draft_id)
            if draft is None:
                continue

            # Only purge aborted or error drafts
            if draft.status not in ("aborted", "error"):
                continue

            # Check the updated_at or created_at timestamp
            timestamp_str = draft.updated_at or draft.created_at
            if not timestamp_str:
                continue

            try:
                draft_time = datetime.fromisoformat(timestamp_str)
                # Ensure timezone-aware comparison
                if draft_time.tzinfo is None:
                    draft_time = draft_time.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue

            if draft_time < cutoff:
                path = self._draft_path(draft_id)
                try:
                    path.unlink()
                    purged_count += 1
                except OSError:
                    pass

        return purged_count
