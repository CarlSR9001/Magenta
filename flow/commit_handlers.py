"""Commit handlers for Bluesky side effects."""

from __future__ import annotations

from .bsky_api import BskyApi
from .models import CommitResult, Draft


def _get_api(draft: Draft) -> BskyApi:
    return BskyApi()


def commit_post(draft: Draft) -> CommitResult:
    if not draft.text:
        return CommitResult(success=False, error="missing_text")
    api = _get_api(draft)
    quote_uri = draft.metadata.get("quote_uri") if draft.metadata else None
    text = draft.text
    if quote_uri:
        text = f"{text}\n\n🔗 {quote_uri}"
    try:
        result = api.create_post(text)
        return CommitResult(success=True, external_uri=result.get("uri"))
    except Exception as exc:
        return CommitResult(success=False, error=str(exc))


def commit_reply(draft: Draft) -> CommitResult:
    if not draft.text:
        return CommitResult(success=False, error="missing_text")
    api = _get_api(draft)
    reply_to = draft.metadata.get("reply_to") if draft.metadata else None
    if not reply_to:
        return CommitResult(success=False, error="missing_reply_context")
    try:
        result = api.create_post(draft.text, reply=reply_to)
        return CommitResult(success=True, external_uri=result.get("uri"))
    except Exception as exc:
        return CommitResult(success=False, error=str(exc))


def commit_like(draft: Draft) -> CommitResult:
    api = _get_api(draft)
    uri = draft.metadata.get("target_uri") if draft.metadata else draft.target_uri
    cid = draft.metadata.get("cid") if draft.metadata else None
    if not uri or not cid:
        return CommitResult(success=False, error="missing_uri_or_cid")
    try:
        result = api.like(uri, cid)
        return CommitResult(success=True, external_uri=result.get("uri"))
    except Exception as exc:
        return CommitResult(success=False, error=str(exc))


def commit_follow(draft: Draft) -> CommitResult:
    api = _get_api(draft)
    actor = draft.metadata.get("actor") if draft.metadata else None
    if not actor:
        return CommitResult(success=False, error="missing_actor")
    try:
        result = api.follow(actor)
        return CommitResult(success=True, external_uri=result.get("uri"))
    except Exception as exc:
        return CommitResult(success=False, error=str(exc))


def commit_mute(draft: Draft) -> CommitResult:
    api = _get_api(draft)
    actor = draft.metadata.get("actor") if draft.metadata else None
    if not actor:
        return CommitResult(success=False, error="missing_actor")
    try:
        api.mute(actor)
        return CommitResult(success=True)
    except Exception as exc:
        return CommitResult(success=False, error=str(exc))


def commit_block(draft: Draft) -> CommitResult:
    api = _get_api(draft)
    actor = draft.metadata.get("actor") if draft.metadata else None
    if not actor:
        return CommitResult(success=False, error="missing_actor")
    try:
        result = api.block(actor)
        return CommitResult(success=True, external_uri=result.get("uri"))
    except Exception as exc:
        return CommitResult(success=False, error=str(exc))
