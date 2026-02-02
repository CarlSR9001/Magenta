"""Simplified commit tools for Bluesky with direct parameters."""


def bsky_publish_reply(
    text: str,
    parent_uri: str,
    parent_cid: str,
    root_uri: str = "",
    root_cid: str = "",
    lang: str = "en-US"
) -> str:
    """
    Reply to a Bluesky post directly.

    Args:
        text: The reply text (max 300 chars). For thread replies, pass JSON array: '["reply1", "reply2"]'
        parent_uri: AT Protocol URI of the post to reply to
        parent_cid: CID of the post to reply to
        root_uri: Optional root thread URI (defaults to parent_uri)
        root_cid: Optional root thread CID (defaults to parent_cid)
        lang: Language code (default: en-US)

    Returns:
        Success message with post URL
    """
    import os
    import json
    import requests
    import re
    from datetime import datetime, timezone

    # Validate URI/CID parameters BEFORE attempting API calls
    # This catches cross-platform confusion (e.g., Moltbook post IDs passed to Bluesky)
    if not parent_uri or not parent_uri.strip():
        return "Error: parent_uri is required. This must be an AT Protocol URI (at://did:plc:.../app.bsky.feed.post/...)"
    if not parent_uri.startswith("at://"):
        return f"Error: parent_uri must be an AT Protocol URI starting with 'at://'. Got: '{parent_uri[:50]}...'. Are you trying to reply to a Moltbook post? Use moltbook_add_comment instead."
    if not parent_cid or not parent_cid.strip():
        return "Error: parent_cid is required. Get this from the notification or bsky_get_thread."

    # Auth
    username = os.getenv("BSKY_USERNAME")
    password = os.getenv("BSKY_PASSWORD")
    pds_host = os.getenv("PDS_URI", "https://bsky.social").rstrip("/")
    if not username or not password:
        return "Error: BSKY_USERNAME and BSKY_PASSWORD must be set"

    try:
        session_url = f"{pds_host}/xrpc/com.atproto.server.createSession"
        session_resp = requests.post(session_url, json={"identifier": username, "password": password}, timeout=10)
        session_resp.raise_for_status()
        session = session_resp.json()
        access_token = session["accessJwt"]
        user_did = session["did"]

        # Parse text - handle JSON array for threads
        if text.strip().startswith("["):
            try:
                parsed = json.loads(text)
                post_texts = parsed if isinstance(parsed, list) else [text]
            except json.JSONDecodeError:
                post_texts = [text]
        else:
            post_texts = [text]

        if not post_texts:
            return "Error: Text cannot be empty"

        results = []
        current_parent_uri = parent_uri
        current_parent_cid = parent_cid
        current_root_uri = root_uri if root_uri else parent_uri
        current_root_cid = root_cid if root_cid else parent_cid

        for i, post_text in enumerate(post_texts):
            if not post_text or not post_text.strip():
                return f"Error: Post {i} text cannot be empty"
            if len(post_text) > 300:
                return f"Error: Post {i} exceeds 300 chars ({len(post_text)})"

            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            record = {
                "$type": "app.bsky.feed.post",
                "text": post_text,
                "createdAt": now,
                "langs": [lang],
                "reply": {
                    "root": {"uri": current_root_uri, "cid": current_root_cid},
                    "parent": {"uri": current_parent_uri, "cid": current_parent_cid}
                }
            }

            headers = {"Authorization": f"Bearer {access_token}"}
            create_url = f"{pds_host}/xrpc/com.atproto.repo.createRecord"
            create_data = {"repo": user_did, "collection": "app.bsky.feed.post", "record": record}

            resp = requests.post(create_url, headers=headers, json=create_data, timeout=10)
            resp.raise_for_status()
            result = resp.json()

            current_parent_uri = result.get("uri")
            current_parent_cid = result.get("cid")
            results.append(result)

        rkey = results[-1].get("uri", "").split("/")[-1]
        handle = session.get("handle", username)
        post_url = f"https://bsky.app/profile/{handle}/post/{rkey}"

        return f"Reply ({len(post_texts)} posts) success!\nURL: {post_url}"
    except Exception as e:
        return f"Error: {e}"


def bsky_publish_post(
    text: str,
    lang: str = "en-US"
) -> str:
    """
    Create a new standalone Bluesky post or thread.

    Args:
        text: The post text (max 300 chars). For threads, pass JSON array: '["post1", "post2"]'
        lang: Language code (default: en-US)

    Returns:
        Success message with post URL
    """
    import os
    import json
    import requests
    from datetime import datetime, timezone

    # Auth
    username = os.getenv("BSKY_USERNAME")
    password = os.getenv("BSKY_PASSWORD")
    pds_host = os.getenv("PDS_URI", "https://bsky.social").rstrip("/")
    if not username or not password:
        return "Error: BSKY_USERNAME and BSKY_PASSWORD must be set"

    try:
        session_url = f"{pds_host}/xrpc/com.atproto.server.createSession"
        session_resp = requests.post(session_url, json={"identifier": username, "password": password}, timeout=10)
        session_resp.raise_for_status()
        session = session_resp.json()
        access_token = session["accessJwt"]
        user_did = session["did"]

        # Parse text - handle JSON array for threads
        if text.strip().startswith("["):
            try:
                parsed = json.loads(text)
                post_texts = parsed if isinstance(parsed, list) else [text]
            except json.JSONDecodeError:
                post_texts = [text]
        else:
            post_texts = [text]

        if not post_texts:
            return "Error: Text cannot be empty"

        results = []
        current_parent_uri = None
        current_parent_cid = None
        current_root_uri = None
        current_root_cid = None

        for i, post_text in enumerate(post_texts):
            if not post_text or not post_text.strip():
                return f"Error: Post {i} text cannot be empty"
            if len(post_text) > 300:
                return f"Error: Post {i} exceeds 300 chars ({len(post_text)})"

            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            record = {
                "$type": "app.bsky.feed.post",
                "text": post_text,
                "createdAt": now,
                "langs": [lang]
            }

            if current_parent_uri:
                record["reply"] = {
                    "root": {"uri": current_root_uri, "cid": current_root_cid},
                    "parent": {"uri": current_parent_uri, "cid": current_parent_cid}
                }

            headers = {"Authorization": f"Bearer {access_token}"}
            create_url = f"{pds_host}/xrpc/com.atproto.repo.createRecord"
            create_data = {"repo": user_did, "collection": "app.bsky.feed.post", "record": record}

            resp = requests.post(create_url, headers=headers, json=create_data, timeout=10)
            resp.raise_for_status()
            result = resp.json()

            if not current_root_uri:
                current_root_uri = result.get("uri")
                current_root_cid = result.get("cid")

            current_parent_uri = result.get("uri")
            current_parent_cid = result.get("cid")
            results.append(result)

        rkey = results[-1].get("uri", "").split("/")[-1]
        handle = session.get("handle", username)
        post_url = f"https://bsky.app/profile/{handle}/post/{rkey}"

        return f"Post ({len(post_texts)} posts) success!\nURL: {post_url}"
    except Exception as e:
        return f"Error: {e}"


def bsky_like(uri: str, cid: str) -> str:
    """Like a Bluesky post.

    Args:
        uri: AT Protocol URI of the post to like (at://did:plc:.../app.bsky.feed.post/...)
        cid: Content ID (CID) of the post to like

    Returns:
        Success message or error
    """
    import os
    import requests
    from datetime import datetime, timezone

    if not uri or not uri.startswith("at://"):
        return "Error: uri must be a valid AT Protocol URI"
    if not cid:
        return "Error: cid is required"

    username = os.getenv("BSKY_USERNAME")
    password = os.getenv("BSKY_PASSWORD")
    pds_host = os.getenv("PDS_URI", "https://bsky.social").rstrip("/")
    if not username or not password:
        return "Error: BSKY_USERNAME and BSKY_PASSWORD must be set"

    try:
        session_url = f"{pds_host}/xrpc/com.atproto.server.createSession"
        session_resp = requests.post(session_url, json={"identifier": username, "password": password}, timeout=10)
        session_resp.raise_for_status()
        session = session_resp.json()
        access_token = session["accessJwt"]
        user_did = session["did"]

        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        record = {
            "$type": "app.bsky.feed.like",
            "subject": {"uri": uri, "cid": cid},
            "createdAt": now
        }

        headers = {"Authorization": f"Bearer {access_token}"}
        create_url = f"{pds_host}/xrpc/com.atproto.repo.createRecord"
        create_data = {"repo": user_did, "collection": "app.bsky.feed.like", "record": record}

        resp = requests.post(create_url, headers=headers, json=create_data, timeout=10)
        resp.raise_for_status()

        return f"Liked: {uri}"
    except Exception as e:
        return f"Error: {e}"


def bsky_follow(did: str) -> str:
    """Follow a Bluesky user.

    Args:
        did: DID or handle of the user to follow (did:plc:... or user.bsky.social)

    Returns:
        Success message or error
    """
    import os
    import requests
    from datetime import datetime, timezone

    if not did:
        return "Error: did is required"

    username = os.getenv("BSKY_USERNAME")
    password = os.getenv("BSKY_PASSWORD")
    pds_host = os.getenv("PDS_URI", "https://bsky.social").rstrip("/")
    if not username or not password:
        return "Error: BSKY_USERNAME and BSKY_PASSWORD must be set"

    try:
        session_url = f"{pds_host}/xrpc/com.atproto.server.createSession"
        session_resp = requests.post(session_url, json={"identifier": username, "password": password}, timeout=10)
        session_resp.raise_for_status()
        session = session_resp.json()
        access_token = session["accessJwt"]
        user_did = session["did"]

        target_did = did.strip()
        if target_did.startswith("@"):
            target_did = target_did[1:]
        if not target_did.startswith("did:"):
            resolve_url = f"{pds_host}/xrpc/com.atproto.identity.resolveHandle"
            resolve_resp = requests.get(resolve_url, params={"handle": target_did}, timeout=10)
            resolve_resp.raise_for_status()
            target_did = resolve_resp.json().get("did", target_did)

        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        record = {
            "$type": "app.bsky.graph.follow",
            "subject": target_did,
            "createdAt": now
        }

        headers = {"Authorization": f"Bearer {access_token}"}
        create_url = f"{pds_host}/xrpc/com.atproto.repo.createRecord"
        create_data = {"repo": user_did, "collection": "app.bsky.graph.follow", "record": record}

        resp = requests.post(create_url, headers=headers, json=create_data, timeout=10)
        resp.raise_for_status()

        return f"Following: {target_did}"
    except Exception as e:
        return f"Error: {e}"


def bsky_mute(did: str) -> str:
    """Mute a Bluesky user.

    Args:
        did: DID or handle of the user to mute (did:plc:... or user.bsky.social)

    Returns:
        Success message or error
    """
    import os
    import requests

    if not did:
        return "Error: did is required"

    username = os.getenv("BSKY_USERNAME")
    password = os.getenv("BSKY_PASSWORD")
    pds_host = os.getenv("PDS_URI", "https://bsky.social").rstrip("/")
    if not username or not password:
        return "Error: BSKY_USERNAME and BSKY_PASSWORD must be set"

    try:
        session_url = f"{pds_host}/xrpc/com.atproto.server.createSession"
        session_resp = requests.post(session_url, json={"identifier": username, "password": password}, timeout=10)
        session_resp.raise_for_status()
        session = session_resp.json()
        access_token = session["accessJwt"]

        target_did = did.strip()
        if target_did.startswith("@"):
            target_did = target_did[1:]
        if not target_did.startswith("did:"):
            resolve_url = f"{pds_host}/xrpc/com.atproto.identity.resolveHandle"
            resolve_resp = requests.get(resolve_url, params={"handle": target_did}, timeout=10)
            resolve_resp.raise_for_status()
            target_did = resolve_resp.json().get("did", target_did)

        mute_url = f"{pds_host}/xrpc/app.bsky.graph.muteActor"
        headers = {"Authorization": f"Bearer {access_token}"}
        resp = requests.post(mute_url, headers=headers, json={"actor": target_did}, timeout=10)
        resp.raise_for_status()

        return f"Muted: {target_did}"
    except Exception as e:
        return f"Error: {e}"


def bsky_block(did: str) -> str:
    """Block a Bluesky user.

    Args:
        did: DID or handle of the user to block (did:plc:... or user.bsky.social)

    Returns:
        Success message or error
    """
    import os
    import requests
    from datetime import datetime, timezone

    if not did:
        return "Error: did is required"

    username = os.getenv("BSKY_USERNAME")
    password = os.getenv("BSKY_PASSWORD")
    pds_host = os.getenv("PDS_URI", "https://bsky.social").rstrip("/")
    if not username or not password:
        return "Error: BSKY_USERNAME and BSKY_PASSWORD must be set"

    try:
        session_url = f"{pds_host}/xrpc/com.atproto.server.createSession"
        session_resp = requests.post(session_url, json={"identifier": username, "password": password}, timeout=10)
        session_resp.raise_for_status()
        session = session_resp.json()
        access_token = session["accessJwt"]
        user_did = session["did"]

        target_did = did.strip()
        if target_did.startswith("@"):
            target_did = target_did[1:]
        if not target_did.startswith("did:"):
            resolve_url = f"{pds_host}/xrpc/com.atproto.identity.resolveHandle"
            resolve_resp = requests.get(resolve_url, params={"handle": target_did}, timeout=10)
            resolve_resp.raise_for_status()
            target_did = resolve_resp.json().get("did", target_did)

        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        record = {
            "$type": "app.bsky.graph.block",
            "subject": target_did,
            "createdAt": now
        }

        headers = {"Authorization": f"Bearer {access_token}"}
        create_url = f"{pds_host}/xrpc/com.atproto.repo.createRecord"
        create_data = {"repo": user_did, "collection": "app.bsky.graph.block", "record": record}

        resp = requests.post(create_url, headers=headers, json=create_data, timeout=10)
        resp.raise_for_status()

        return f"Blocked: {target_did}"
    except Exception as e:
        return f"Error: {e}"
