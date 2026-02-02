"""Commit side-effect actions based on drafts."""

from __future__ import annotations

from typing import Callable, Dict, Optional

from .models import CommitResult, Draft, DraftType


class CommitDispatcher:
    def __init__(self, handlers: Dict[DraftType, Callable[[Draft], CommitResult]]) -> None:
        self.handlers = handlers

    def commit(self, draft: Draft) -> CommitResult:
        handler = self.handlers.get(draft.type)
        if not handler:
            return CommitResult(success=False, error=f"No commit handler for {draft.type}")
        return handler(draft)


def not_implemented_commit(_: Draft) -> CommitResult:
    return CommitResult(success=False, error="Commit handler not implemented")
