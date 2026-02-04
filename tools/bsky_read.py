"""Read-only Bluesky tools.

These tools provide read access to Bluesky data.
"""

from pydantic import BaseModel, Field


class ListNotificationsArgs(BaseModel):
    limit: int = Field(default=20, ge=1, le=50)
    only_new: bool = Field(default=False, description="Filter out notifications already in the database")


def bsky_list_notifications(limit: int = 20, only_new: bool = False) -> str:
    """List recent Bluesky notifications.

    Args:
        limit: Number of notifications to fetch (1-50, default 20).
        only_new: If True, filter out notifications already in the database.

    Returns:
        YAML-formatted list of notifications.
    """
    import os
    import requests
    import yaml

    username = os.getenv("BSKY_USERNAME")
    password = os.getenv("BSKY_PASSWORD")
    pds_host = os.getenv("PDS_URI", "https://bsky.social").rstrip("/")
    if not username or not password:
        try:
            from config_loader import get_bluesky_config
            cfg = get_bluesky_config()
            username = username or cfg.get("username")
            password = password or cfg.get("password")
            pds_host = (cfg.get("pds_uri") or pds_host).rstrip("/")
        except Exception:
            pass
    if not username or not password:
        return "Error: BSKY_USERNAME and BSKY_PASSWORD must be set"

    try:
        session_url = f"{pds_host}/xrpc/com.atproto.server.createSession"
        session_response = requests.post(session_url, json={"identifier": username, "password": password}, timeout=10)
        session_response.raise_for_status()
        access_token = session_response.json()["accessJwt"]

        url = f"{pds_host}/xrpc/app.bsky.notification.listNotifications"
        resp = requests.get(url, headers={"Authorization": f"Bearer {access_token}"}, params={"limit": limit}, timeout=10)
        resp.raise_for_status()

        notifications = resp.json().get("notifications", [])

        if only_new:
            try:
                from notification_db import NotificationDB
                db = NotificationDB()
                processed = db.get_all_processed_uris()
                notifications = [n for n in notifications if n.get("uri") not in processed]
            except Exception:
                try:
                    from letta_client import Letta
                    import json

                    api_key = os.getenv("LETTA_API_KEY")
                    agent_id = os.getenv("LETTA_AGENT_ID")
                    base_url = os.getenv("LETTA_BASE_URL")
                    if not api_key or not agent_id:
                        raise RuntimeError("LETTA_API_KEY and LETTA_AGENT_ID must be set for fallback")

                    client = Letta(api_key=api_key, base_url=base_url) if base_url else Letta(api_key=api_key)
                    marker = "[BSKY_NOTIFICATION_DB]"
                    passages = client.agents.passages.list(agent_id=agent_id, search=marker, limit=5)
                    items = getattr(passages, "items", passages) if passages else []
                    state = {}
                    for passage in items:
                        text = getattr(passage, "text", "")
                        if text.startswith(marker):
                            json_str = text[len(marker):].strip()
                            state = json.loads(json_str) if json_str else {}
                            break

                    processed_map = state.get("processed", {})
                    notifications = [n for n in notifications if n.get("uri") not in processed_map]
                except Exception:
                    pass  # Continue with unfiltered if fallback unavailable

        return yaml.dump(notifications, default_flow_style=False, sort_keys=False, allow_unicode=True)
    except Exception as e:
        return f"Error: {e}"


class GetThreadArgs(BaseModel):
    uri: str = Field(default="", description="AT URI or bsky.app URL of the post")
    depth: int = Field(default=10, ge=1, le=20)
    parent_height: int = Field(default=80, ge=0, le=100)


def bsky_get_thread(uri: str = "", depth: int = 10, parent_height: int = 80) -> str:
    """Get a Bluesky thread starting from a specific post.

    Args:
        uri: AT URI or bsky.app URL. Required.
        depth: How many levels of replies to fetch (1-20, default 10).
        parent_height: How many parent posts to fetch (0-100, default 80).

    Returns:
        YAML-formatted thread data.
    """
    import os
    import requests
    import yaml

    uri = uri.strip() if uri else ""
    if not uri:
        return "Error: uri is required. Provide an AT URI or bsky.app URL."

    username = os.getenv("BSKY_USERNAME")
    password = os.getenv("BSKY_PASSWORD")
    pds_host = os.getenv("PDS_URI", "https://bsky.social").rstrip("/")
    if not username or not password:
        try:
            from config_loader import get_bluesky_config
            cfg = get_bluesky_config()
            username = username or cfg.get("username")
            password = password or cfg.get("password")
            pds_host = (cfg.get("pds_uri") or pds_host).rstrip("/")
        except Exception:
            pass
    if not username or not password:
        return "Error: BSKY_USERNAME and BSKY_PASSWORD must be set"

    try:
        # Convert bsky.app URL to AT URI if needed
        if "bsky.app/profile/" in uri and "/post/" in uri:
            parts = uri.split("/")
            handle = parts[parts.index("profile") + 1]
            post_id = parts[parts.index("post") + 1]
            if not handle.startswith("did:"):
                resolve_url = f"{pds_host}/xrpc/com.atproto.identity.resolveHandle"
                resolve = requests.get(resolve_url, params={"handle": handle}, timeout=10)
                resolve.raise_for_status()
                handle = resolve.json().get("did")
            uri = f"at://{handle}/app.bsky.feed.post/{post_id}"

        session_url = f"{pds_host}/xrpc/com.atproto.server.createSession"
        session_response = requests.post(session_url, json={"identifier": username, "password": password}, timeout=10)
        session_response.raise_for_status()
        access_token = session_response.json()["accessJwt"]

        url = f"{pds_host}/xrpc/app.bsky.feed.getPostThread"
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            params={"uri": uri, "depth": depth, "parentHeight": parent_height},
            timeout=10,
        )
        resp.raise_for_status()

        return yaml.dump(resp.json(), default_flow_style=False, sort_keys=False, allow_unicode=True)
    except Exception as e:
        return f"Error: {e}"


class GetProfileArgs(BaseModel):
    actor: str = Field(default="", description="Handle or DID")


def bsky_get_profile(actor: str = "") -> str:
    """Get a Bluesky user's profile.

    Args:
        actor: Handle or DID of the user.

    Returns:
        Profile data as string.
    """
    import os
    import requests

    actor = actor.strip()
    if not actor:
        return "Error: actor is required"

    username = os.getenv("BSKY_USERNAME")
    password = os.getenv("BSKY_PASSWORD")
    pds_host = os.getenv("PDS_URI", "https://bsky.social").rstrip("/")
    if not username or not password:
        try:
            from config_loader import get_bluesky_config
            cfg = get_bluesky_config()
            username = username or cfg.get("username")
            password = password or cfg.get("password")
            pds_host = (cfg.get("pds_uri") or pds_host).rstrip("/")
        except Exception:
            pass
    if not username or not password:
        return "Error: BSKY_USERNAME and BSKY_PASSWORD must be set"

    try:
        session_url = f"{pds_host}/xrpc/com.atproto.server.createSession"
        session_response = requests.post(session_url, json={"identifier": username, "password": password}, timeout=10)
        session_response.raise_for_status()
        access_token = session_response.json()["accessJwt"]

        if actor.startswith("@"):
            actor = actor[1:]
        if not actor.startswith("did:"):
            resolve_url = f"{pds_host}/xrpc/com.atproto.identity.resolveHandle"
            resolve = requests.get(resolve_url, headers={"Authorization": f"Bearer {access_token}"}, params={"handle": actor}, timeout=10)
            resolve.raise_for_status()
            actor = resolve.json().get("did") or actor

        url = f"{pds_host}/xrpc/app.bsky.actor.getProfile"
        resp = requests.get(url, headers={"Authorization": f"Bearer {access_token}"}, params={"actor": actor}, timeout=10)
        resp.raise_for_status()
        return str(resp.json())
    except Exception as e:
        return f"Error: {e}"


class MarkNotificationProcessedArgs(BaseModel):
    uri: str = Field(..., description="URI of the notification to mark as processed")
    reason: str = Field(default="replied", description="Why it was processed (replied, skipped, irrelevant)")


def bsky_mark_notification_processed(uri: str, reason: str = "replied") -> str:
    """Mark a Bluesky notification as processed so it won't appear again.

    IMPORTANT: Call this AFTER you successfully reply to or handle a notification.
    This prevents the same notification from appearing in future social signals.

    Args:
        uri: The notification URI (from bsky_list_notifications output)
        reason: Why it was processed (replied, skipped, irrelevant, etc.)

    Returns:
        Success/error message
    """
    if not uri:
        return "Error: uri is required"

    try:
        from notification_db import NotificationDB
        db = NotificationDB()
        db.mark_processed(uri, status="processed", reason=reason)
        db.close()
        return f"Marked as processed: {uri} (reason: {reason})"
    except Exception as e:
        try:
            import os
            import json
            from datetime import datetime, timezone
            from letta_client import Letta

            api_key = os.getenv("LETTA_API_KEY")
            agent_id = os.getenv("LETTA_AGENT_ID")
            base_url = os.getenv("LETTA_BASE_URL")
            if not api_key or not agent_id:
                return f"Error marking notification: {e}"

            client = Letta(api_key=api_key, base_url=base_url) if base_url else Letta(api_key=api_key)
            marker = "[BSKY_NOTIFICATION_DB]"
            passages = client.agents.passages.list(agent_id=agent_id, search=marker, limit=10)
            items = getattr(passages, "items", passages) if passages else []

            state = {}
            old_passage_ids = []
            for passage in items:
                text = getattr(passage, "text", "")
                if text.startswith(marker):
                    json_str = text[len(marker):].strip()
                    state = json.loads(json_str) if json_str else {}
                    passage_id = getattr(passage, "id", None)
                    if passage_id:
                        old_passage_ids.append(str(passage_id))

            processed = state.get("processed", {})
            processed[uri] = {
                "status": "processed",
                "reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            state["processed"] = processed

            for passage_id in old_passage_ids:
                try:
                    client.agents.passages.delete(passage_id, agent_id=agent_id)
                except Exception:
                    pass

            state_json = json.dumps(state, indent=2, sort_keys=True)
            client.agents.passages.create(agent_id=agent_id, text=f"{marker}\n{state_json}")
            return f"Marked as processed: {uri} (reason: {reason})"
        except Exception as fallback_error:
            return f"Error marking notification: {e}; fallback failed: {fallback_error}"


def bsky_mark_notifications_batch(uris: str) -> str:
    """Mark multiple notifications as processed at once.

    Args:
        uris: Comma-separated list of notification URIs to mark

    Returns:
        Success/error message with count
    """
    if not uris:
        return "Error: uris is required (comma-separated)"

    uri_list = [u.strip() for u in uris.split(",") if u.strip()]
    if not uri_list:
        return "Error: No valid URIs provided"

    try:
        from notification_db import NotificationDB
        db = NotificationDB()
        for uri in uri_list:
            db.mark_processed(uri, status="processed", reason="batch")
        db.close()
        return f"Marked {len(uri_list)} notifications as processed"
    except Exception as e:
        try:
            import os
            import json
            from datetime import datetime, timezone
            from letta_client import Letta

            api_key = os.getenv("LETTA_API_KEY")
            agent_id = os.getenv("LETTA_AGENT_ID")
            base_url = os.getenv("LETTA_BASE_URL")
            if not api_key or not agent_id:
                return f"Error: {e}"

            client = Letta(api_key=api_key, base_url=base_url) if base_url else Letta(api_key=api_key)
            marker = "[BSKY_NOTIFICATION_DB]"
            passages = client.agents.passages.list(agent_id=agent_id, search=marker, limit=10)
            items = getattr(passages, "items", passages) if passages else []

            state = {}
            old_passage_ids = []
            for passage in items:
                text = getattr(passage, "text", "")
                if text.startswith(marker):
                    json_str = text[len(marker):].strip()
                    state = json.loads(json_str) if json_str else {}
                    passage_id = getattr(passage, "id", None)
                    if passage_id:
                        old_passage_ids.append(str(passage_id))

            processed = state.get("processed", {})
            timestamp = datetime.now(timezone.utc).isoformat()
            for uri in uri_list:
                processed[uri] = {
                    "status": "processed",
                    "reason": "batch",
                    "timestamp": timestamp,
                }
            state["processed"] = processed

            for passage_id in old_passage_ids:
                try:
                    client.agents.passages.delete(passage_id, agent_id=agent_id)
                except Exception:
                    pass

            state_json = json.dumps(state, indent=2, sort_keys=True)
            client.agents.passages.create(agent_id=agent_id, text=f"{marker}\n{state_json}")
            return f"Marked {len(uri_list)} notifications as processed"
        except Exception as fallback_error:
            return f"Error: {e}; fallback failed: {fallback_error}"
