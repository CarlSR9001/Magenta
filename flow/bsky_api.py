"""Minimal Bluesky HTTP client for read-only and commit actions."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests


class BskyApi:
    def __init__(self, username: Optional[str] = None, password: Optional[str] = None, pds_uri: Optional[str] = None) -> None:
        self.username = username or os.getenv("BSKY_USERNAME")
        self.password = password or os.getenv("BSKY_PASSWORD")
        self.pds_host = (pds_uri or os.getenv("PDS_URI", "https://bsky.social")).rstrip("/")
        if not self.username or not self.password or not pds_uri:
            try:
                from config_loader import get_bluesky_config
                cfg = get_bluesky_config()
                self.username = self.username or cfg.get("username")
                self.password = self.password or cfg.get("password")
                if not pds_uri:
                    self.pds_host = (cfg.get("pds_uri") or self.pds_host).rstrip("/")
            except Exception:
                pass
        self._access_token: Optional[str] = None
        self._did: Optional[str] = None

    def _request(self, method: str, url: str, **kwargs):
        if "headers" not in kwargs or kwargs["headers"] is None:
            kwargs["headers"] = self.headers
        resp = requests.request(method, url, **kwargs)
        if resp.status_code == 401:
            self._access_token = None
            self._did = None
            kwargs["headers"] = self.headers
            resp = requests.request(method, url, **kwargs)
        return resp

    def _ensure_session(self) -> None:
        if self._access_token and self._did:
            return
        if not self.username or not self.password:
            raise ValueError("BSKY_USERNAME and BSKY_PASSWORD must be set")
        session_url = f"{self.pds_host}/xrpc/com.atproto.server.createSession"
        resp = requests.post(session_url, json={"identifier": self.username, "password": self.password}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["accessJwt"]
        self._did = data["did"]

    @property
    def did(self) -> str:
        self._ensure_session()
        assert self._did
        return self._did

    @property
    def headers(self) -> Dict[str, str]:
        self._ensure_session()
        assert self._access_token
        return {"Authorization": f"Bearer {self._access_token}"}

    def resolve_handle(self, handle_or_did: str) -> str:
        if handle_or_did.startswith("did:"):
            return handle_or_did
        handle = handle_or_did.lstrip("@")
        url = f"{self.pds_host}/xrpc/com.atproto.identity.resolveHandle"
        resp = self._request("GET", url, params={"handle": handle}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        did = data.get("did")
        if not did:
            raise ValueError(f"Failed to resolve handle: {handle}")
        return did

    # ---- Read-only ----
    def list_notifications(self, limit: int = 20) -> List[Dict[str, Any]]:
        url = f"{self.pds_host}/xrpc/app.bsky.notification.listNotifications"
        resp = self._request("GET", url, params={"limit": limit}, timeout=10)
        resp.raise_for_status()
        return resp.json().get("notifications", [])

    def get_post_thread(self, uri: str, depth: int = 6, parent_height: int = 2) -> Dict[str, Any]:
        url = f"{self.pds_host}/xrpc/app.bsky.feed.getPostThread"
        resp = self._request(
            "GET",
            url,
            params={"uri": uri, "depth": depth, "parentHeight": parent_height},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def get_profile(self, actor: str) -> Dict[str, Any]:
        did = self.resolve_handle(actor)
        url = f"{self.pds_host}/xrpc/app.bsky.actor.getProfile"
        resp = self._request("GET", url, params={"actor": did}, timeout=10)
        resp.raise_for_status()
        return resp.json()

    # ---- Commit actions ----
    def create_post(self, text: str, reply: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        record = {
            "$type": "app.bsky.feed.post",
            "text": text,
            "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        if reply:
            record["reply"] = reply
        url = f"{self.pds_host}/xrpc/com.atproto.repo.createRecord"
        payload = {"repo": self.did, "collection": "app.bsky.feed.post", "record": record}
        resp = self._request("POST", url, json=payload, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def like(self, uri: str, cid: str) -> Dict[str, Any]:
        record = {
            "$type": "app.bsky.feed.like",
            "subject": {"uri": uri, "cid": cid},
            "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        url = f"{self.pds_host}/xrpc/com.atproto.repo.createRecord"
        payload = {"repo": self.did, "collection": "app.bsky.feed.like", "record": record}
        resp = self._request("POST", url, json=payload, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def follow(self, actor: str) -> Dict[str, Any]:
        target = self.resolve_handle(actor)
        record = {
            "$type": "app.bsky.graph.follow",
            "subject": target,
            "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        url = f"{self.pds_host}/xrpc/com.atproto.repo.createRecord"
        payload = {"repo": self.did, "collection": "app.bsky.graph.follow", "record": record}
        resp = self._request("POST", url, json=payload, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def mute(self, actor: str) -> Dict[str, Any]:
        target = self.resolve_handle(actor)
        url = f"{self.pds_host}/xrpc/app.bsky.graph.muteActor"
        resp = self._request("POST", url, json={"actor": target}, timeout=10)
        resp.raise_for_status()
        return resp.json() if resp.content else {"status": "muted"}

    def block(self, actor: str) -> Dict[str, Any]:
        target = self.resolve_handle(actor)
        record = {
            "$type": "app.bsky.graph.block",
            "subject": target,
            "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        url = f"{self.pds_host}/xrpc/com.atproto.repo.createRecord"
        payload = {"repo": self.did, "collection": "app.bsky.graph.block", "record": record}
        resp = self._request("POST", url, json=payload, timeout=10)
        resp.raise_for_status()
        return resp.json()
