"""Moltbook tools for Magenta agent.

Moltbook is a social network for AI agents ("moltys").
API Base: https://www.moltbook.com/api/v1
"""

from typing import Optional, Literal
from pydantic import BaseModel, Field


# =============================================================================
# PYDANTIC ARGS SCHEMAS
# =============================================================================

class MoltbookRegisterArgs(BaseModel):
    name: str = Field(..., description="Agent name for Moltbook")
    description: str = Field(..., description="Brief description of what the agent does")


class MoltbookPostArgs(BaseModel):
    title: str = Field(..., description="Post title")
    content: Optional[str] = Field(None, description="Post content (text body)")
    url: Optional[str] = Field(None, description="URL to share (for link posts)")
    submolt: Optional[str] = Field(None, description="Submolt (community) to post in")


class MoltbookGetPostsArgs(BaseModel):
    sort: Literal["hot", "new", "top", "rising"] = Field("hot", description="Sort order")
    limit: int = Field(25, ge=1, le=100, description="Number of posts to fetch")


class MoltbookCommentArgs(BaseModel):
    post_id: str = Field(..., description="Post ID to comment on")
    content: str = Field(..., description="Comment text")
    parent_id: Optional[str] = Field(None, description="Parent comment ID for nested replies")


class MoltbookVoteArgs(BaseModel):
    post_id: str = Field(..., description="Post ID to vote on")
    direction: Literal["up", "down"] = Field("up", description="Vote direction")


class MoltbookCommentVoteArgs(BaseModel):
    comment_id: str = Field(..., description="Comment ID to upvote")


class MoltbookFollowArgs(BaseModel):
    molty_name: str = Field(..., description="Name of the molty to follow")


class MoltbookUnfollowArgs(BaseModel):
    molty_name: str = Field(..., description="Name of the molty to unfollow")


class MoltbookProfileArgs(BaseModel):
    name: Optional[str] = Field(None, description="Molty name to look up (omit for own profile)")


class MoltbookSubmoltArgs(BaseModel):
    name: str = Field(..., description="Submolt slug name (lowercase, no spaces)")
    display_name: str = Field(..., description="Display name for the submolt")
    description: str = Field(..., description="Description of the submolt")


class MoltbookSubscribeArgs(BaseModel):
    submolt_name: str = Field(..., description="Submolt name to subscribe to")


class MoltbookFeedArgs(BaseModel):
    sort: Literal["hot", "new", "top"] = Field("hot", description="Sort order")
    limit: int = Field(25, ge=1, le=100, description="Number of posts to fetch")


class MoltbookSearchArgs(BaseModel):
    query: str = Field(..., description="Search query")
    search_type: Literal["posts", "comments", "all"] = Field("all", description="Type of content to search")
    limit: int = Field(25, ge=1, le=100, description="Number of results")


class MoltbookGetPostArgs(BaseModel):
    post_id: str = Field(..., description="Post ID to retrieve")


class MoltbookGetSubmoltPostsArgs(BaseModel):
    submolt_name: str = Field(..., description="Submolt name to get posts from")
    sort: Literal["hot", "new", "top", "rising"] = Field("hot", description="Sort order")
    limit: int = Field(25, ge=1, le=100, description="Number of posts to fetch")


class MoltbookUpdateProfileArgs(BaseModel):
    description: str = Field(None, description="New profile description")
    metadata: dict = Field(None, description="Additional metadata to update")


class MoltbookGetSubmoltArgs(BaseModel):
    submolt_name: str = Field(..., description="Submolt name to get info for")


class MoltbookUnsubscribeArgs(BaseModel):
    submolt_name: str = Field(..., description="Submolt name to unsubscribe from")


class MoltbookUpdateSubmoltArgs(BaseModel):
    submolt_name: str = Field(..., description="Submolt name to update")
    description: str = Field(None, description="New description")
    primary_color: str = Field(None, description="Primary color (hex)")
    secondary_color: str = Field(None, description="Secondary color (hex)")


class MoltbookModeratorArgs(BaseModel):
    submolt_name: str = Field(..., description="Submolt name")
    molty_name: str = Field(..., description="Molty name to add/remove as moderator")


class MoltbookListModeratorsArgs(BaseModel):
    submolt_name: str = Field(..., description="Submolt name to list moderators for")


class MoltbookPinPostArgs(BaseModel):
    post_id: str = Field(..., description="Post ID to pin/unpin")


class MoltbookGetCommentsArgs(BaseModel):
    post_id: str = Field(..., description="Post ID to get comments from")
    sort: Literal["top", "new", "controversial"] = Field("top", description="Sort order")


class MoltbookDMListArgs(BaseModel):
    pass  # No args needed


class MoltbookDMSendArgs(BaseModel):
    recipient: str = Field(..., description="Recipient molty name")
    content: str = Field(..., description="Message content")


class MoltbookDMReadArgs(BaseModel):
    conversation_id: str = Field(..., description="Conversation ID to read")


# =============================================================================
# TOOL FUNCTIONS
# =============================================================================

def moltbook_register(name: str, description: str) -> str:
    """Register a new agent on Moltbook.

    Returns API key and claim URL for human verification.
    Store credentials in config for future use.
    """
    import os
    import base64
    import json
    import requests

    base_url = "https://www.moltbook.com/api/v1"

    try:
        resp = requests.post(
            f"{base_url}/agents/register",
            headers={"Content-Type": "application/json"},
            json={"name": name, "description": description},
            timeout=30
        )
        resp.raise_for_status()
        data = resp.json()

        result = {
            "status": "success",
            "api_key": data.get("api_key"),
            "claim_url": data.get("claim_url"),
            "verification_code": data.get("verification_code"),
            "message": "Store the api_key in MOLTBOOK_API_KEY env var. Human must visit claim_url to verify ownership."
        }
        return json.dumps(result, indent=2)
    except requests.exceptions.RequestException as e:
        return json.dumps({"status": "error", "error": str(e)})


def moltbook_get_profile(name: str = None) -> str:
    """Get a Moltbook profile.

    If name is omitted, returns your own profile.
    """
    import os
    import json
    import requests

    api_key = os.getenv("MOLTBOOK_API_KEY")
    if not api_key:
        return json.dumps({"status": "error", "error": "MOLTBOOK_API_KEY not set"})

    base_url = "https://www.moltbook.com/api/v1"
    headers = {"X-API-Key": api_key, "Authorization": f"Bearer {api_key}"}

    try:
        if name:
            resp = requests.get(
                f"{base_url}/agents/profile",
                headers=headers,
                params={"name": name},
                timeout=30
            )
        else:
            resp = requests.get(f"{base_url}/agents/me", headers=headers, timeout=30)

        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)
    except requests.exceptions.RequestException as e:
        return json.dumps({"status": "error", "error": str(e)})


def moltbook_get_feed(sort: str = "hot", limit: int = 25) -> str:
    """Get personalized Moltbook feed.

    Shows posts from followed moltys and subscribed submolts.
    """
    import os
    import json
    import requests

    api_key = os.getenv("MOLTBOOK_API_KEY")
    if not api_key:
        return json.dumps({"status": "error", "error": "MOLTBOOK_API_KEY not set"})

    base_url = "https://www.moltbook.com/api/v1"
    headers = {"X-API-Key": api_key, "Authorization": f"Bearer {api_key}"}

    try:
        resp = requests.get(
            f"{base_url}/feed",
            headers=headers,
            params={"sort": sort, "limit": limit},
            timeout=30
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)
    except requests.exceptions.RequestException as e:
        return json.dumps({"status": "error", "error": str(e)})


def moltbook_get_posts(sort: str = "hot", limit: int = 25) -> str:
    """Get posts from Moltbook (global feed).

    Args:
        sort: hot, new, top, or rising
        limit: 1-100
    """
    import os
    import json
    import requests

    api_key = os.getenv("MOLTBOOK_API_KEY")
    if not api_key:
        return json.dumps({"status": "error", "error": "MOLTBOOK_API_KEY not set"})

    base_url = "https://www.moltbook.com/api/v1"
    headers = {"X-API-Key": api_key, "Authorization": f"Bearer {api_key}"}

    try:
        resp = requests.get(
            f"{base_url}/posts",
            headers=headers,
            params={"sort": sort, "limit": limit},
            timeout=30
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)
    except requests.exceptions.RequestException as e:
        return json.dumps({"status": "error", "error": str(e)})


def moltbook_create_post(title: str, content: str = None, url: str = None, submolt: str = None) -> str:
    """Create a new post on Moltbook.

    Rate limit: 1 post per 30 minutes.
    Provide either content (text post) or url (link post).
    """
    import os
    import json
    import requests

    api_key = os.getenv("MOLTBOOK_API_KEY")
    if not api_key:
        return json.dumps({"status": "error", "error": "MOLTBOOK_API_KEY not set"})

    base_url = "https://www.moltbook.com/api/v1"
    headers = {
        "X-API-Key": api_key,
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {"title": title}
    if content:
        payload["content"] = content
    if url:
        payload["url"] = url
    if submolt:
        payload["submolt"] = submolt

    try:
        resp = requests.post(
            f"{base_url}/posts",
            headers=headers,
            json=payload,
            timeout=30
        )

        if resp.status_code == 429:
            data = resp.json()
            return json.dumps({
                "status": "rate_limited",
                "retry_after_minutes": data.get("retry_after_minutes", 30),
                "message": "Post rate limit hit. Wait before posting again."
            })

        resp.raise_for_status()
        return json.dumps({"status": "success", "post": resp.json()})
    except requests.exceptions.RequestException as e:
        return json.dumps({"status": "error", "error": str(e)})


def moltbook_delete_post(post_id: str) -> str:
    """Delete one of your posts.

    Args:
        post_id: The ID of the post to delete
    """
    import os
    import json
    import requests

    api_key = os.getenv("MOLTBOOK_API_KEY")
    if not api_key:
        return json.dumps({"status": "error", "error": "MOLTBOOK_API_KEY not set"})

    base_url = "https://www.moltbook.com/api/v1"
    headers = {"X-API-Key": api_key, "Authorization": f"Bearer {api_key}"}

    try:
        resp = requests.delete(
            f"{base_url}/posts/{post_id}",
            headers=headers,
            timeout=30
        )
        resp.raise_for_status()
        return json.dumps({"status": "success", "message": f"Post {post_id} deleted"})
    except requests.exceptions.RequestException as e:
        return json.dumps({"status": "error", "error": str(e)})


def moltbook_add_comment(post_id: str, content: str, parent_id: str = None) -> str:
    """Add a comment to a post.

    Rate limit: 50 comments per hour.
    Use parent_id to reply to another comment.
    """
    import os
    import json
    import requests

    # Validate parameters - catch cross-platform confusion early
    if not post_id or not str(post_id).strip():
        return json.dumps({"status": "error", "error": "post_id is required"})

    # Check if someone accidentally passed a Bluesky AT URI
    post_id_str = str(post_id)
    if post_id_str.startswith("at://"):
        return json.dumps({
            "status": "error",
            "error": f"post_id looks like a Bluesky AT URI. Are you trying to reply to a Bluesky post? Use bsky_publish_reply instead.",
            "received": post_id_str[:60]
        })

    if not content or not content.strip():
        return json.dumps({"status": "error", "error": "content cannot be empty"})

    api_key = os.getenv("MOLTBOOK_API_KEY")
    if not api_key:
        return json.dumps({"status": "error", "error": "MOLTBOOK_API_KEY not set"})

    base_url = "https://www.moltbook.com/api/v1"
    headers = {
        "X-API-Key": api_key,
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {"content": content}
    if parent_id:
        payload["parent_id"] = parent_id

    try:
        resp = requests.post(
            f"{base_url}/posts/{post_id}/comments",
            headers=headers,
            json=payload,
            timeout=30
        )
        resp.raise_for_status()
        return json.dumps({"status": "success", "comment": resp.json()})
    except requests.exceptions.RequestException as e:
        return json.dumps({"status": "error", "error": str(e)})


def moltbook_get_comments(post_id: str, sort: str = "top") -> str:
    """Get comments on a post.

    Args:
        post_id: The ID of the post to get comments from
        sort: Sort order (top, new, controversial)
    """
    import os
    import json
    import requests

    api_key = os.getenv("MOLTBOOK_API_KEY")
    if not api_key:
        return json.dumps({"status": "error", "error": "MOLTBOOK_API_KEY not set"})

    base_url = "https://www.moltbook.com/api/v1"
    headers = {"X-API-Key": api_key, "Authorization": f"Bearer {api_key}"}
    sort = (sort or "top").lower()

    try:
        resp = requests.get(
            f"{base_url}/posts/{post_id}",
            headers=headers,
            timeout=30
        )
        resp.raise_for_status()
        payload = resp.json()
        comments = payload.get("comments") if isinstance(payload, dict) else None

        if isinstance(comments, list):
            if sort == "new":
                comments = sorted(
                    comments,
                    key=lambda c: c.get("created_at") or "",
                    reverse=True
                )
            elif sort == "controversial":
                comments = sorted(
                    comments,
                    key=lambda c: (
                        (c.get("upvotes", 0) + c.get("downvotes", 0)),
                        -(abs((c.get("upvotes", 0) - c.get("downvotes", 0))))
                    ),
                    reverse=True
                )
            else:
                comments = sorted(
                    comments,
                    key=lambda c: (
                        (c.get("upvotes", 0) - c.get("downvotes", 0)),
                        c.get("upvotes", 0)
                    ),
                    reverse=True
                )
            payload["comments"] = comments

        return json.dumps(payload, indent=2)
    except requests.exceptions.RequestException as e:
        return json.dumps({"status": "error", "error": str(e)})


def moltbook_upvote_post(post_id: str) -> str:
    """Upvote a post.

    Args:
        post_id: The ID of the post to upvote
    """
    import os
    import json
    import requests

    api_key = os.getenv("MOLTBOOK_API_KEY")
    if not api_key:
        return json.dumps({"status": "error", "error": "MOLTBOOK_API_KEY not set"})

    base_url = "https://www.moltbook.com/api/v1"
    headers = {"X-API-Key": api_key, "Authorization": f"Bearer {api_key}"}

    try:
        resp = requests.post(
            f"{base_url}/posts/{post_id}/upvote",
            headers=headers,
            timeout=30
        )
        resp.raise_for_status()
        return json.dumps({"status": "success", "message": f"Upvoted post {post_id}"})
    except requests.exceptions.RequestException as e:
        return json.dumps({"status": "error", "error": str(e)})


def moltbook_downvote_post(post_id: str) -> str:
    """Downvote a post.

    Args:
        post_id: The ID of the post to downvote
    """
    import os
    import json
    import requests

    api_key = os.getenv("MOLTBOOK_API_KEY")
    if not api_key:
        return json.dumps({"status": "error", "error": "MOLTBOOK_API_KEY not set"})

    base_url = "https://www.moltbook.com/api/v1"
    headers = {"X-API-Key": api_key, "Authorization": f"Bearer {api_key}"}

    try:
        resp = requests.post(
            f"{base_url}/posts/{post_id}/downvote",
            headers=headers,
            timeout=30
        )
        resp.raise_for_status()
        return json.dumps({"status": "success", "message": f"Downvoted post {post_id}"})
    except requests.exceptions.RequestException as e:
        return json.dumps({"status": "error", "error": str(e)})


def moltbook_upvote_comment(comment_id: str) -> str:
    """Upvote a comment.

    Args:
        comment_id: The ID of the comment to upvote
    """
    import os
    import json
    import requests

    api_key = os.getenv("MOLTBOOK_API_KEY")
    if not api_key:
        return json.dumps({"status": "error", "error": "MOLTBOOK_API_KEY not set"})

    base_url = "https://www.moltbook.com/api/v1"
    headers = {"X-API-Key": api_key, "Authorization": f"Bearer {api_key}"}

    try:
        resp = requests.post(
            f"{base_url}/comments/{comment_id}/upvote",
            headers=headers,
            timeout=30
        )
        resp.raise_for_status()
        return json.dumps({"status": "success", "message": f"Upvoted comment {comment_id}"})
    except requests.exceptions.RequestException as e:
        return json.dumps({"status": "error", "error": str(e)})


def moltbook_follow(molty_name: str) -> str:
    """Follow a molty.

    Follow sparingly - only after seeing multiple valuable posts.
    """
    import os
    import json
    import requests

    api_key = os.getenv("MOLTBOOK_API_KEY")
    if not api_key:
        return json.dumps({"status": "error", "error": "MOLTBOOK_API_KEY not set"})

    base_url = "https://www.moltbook.com/api/v1"
    headers = {"X-API-Key": api_key, "Authorization": f"Bearer {api_key}"}

    try:
        resp = requests.post(
            f"{base_url}/agents/{molty_name}/follow",
            headers=headers,
            timeout=30
        )
        resp.raise_for_status()
        return json.dumps({"status": "success", "message": f"Now following {molty_name}"})
    except requests.exceptions.RequestException as e:
        return json.dumps({"status": "error", "error": str(e)})


def moltbook_unfollow(molty_name: str) -> str:
    """Unfollow a molty."""
    import os
    import json
    import requests

    api_key = os.getenv("MOLTBOOK_API_KEY")
    if not api_key:
        return json.dumps({"status": "error", "error": "MOLTBOOK_API_KEY not set"})

    base_url = "https://www.moltbook.com/api/v1"
    headers = {"X-API-Key": api_key, "Authorization": f"Bearer {api_key}"}

    try:
        resp = requests.delete(
            f"{base_url}/agents/{molty_name}/follow",
            headers=headers,
            timeout=30
        )
        resp.raise_for_status()
        return json.dumps({"status": "success", "message": f"Unfollowed {molty_name}"})
    except requests.exceptions.RequestException as e:
        return json.dumps({"status": "error", "error": str(e)})


def moltbook_list_submolts() -> str:
    """List available submolts (communities)."""
    import os
    import json
    import requests

    api_key = os.getenv("MOLTBOOK_API_KEY")
    if not api_key:
        return json.dumps({"status": "error", "error": "MOLTBOOK_API_KEY not set"})

    base_url = "https://www.moltbook.com/api/v1"
    headers = {"X-API-Key": api_key, "Authorization": f"Bearer {api_key}"}

    try:
        resp = requests.get(f"{base_url}/submolts", headers=headers, timeout=30)
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)
    except requests.exceptions.RequestException as e:
        return json.dumps({"status": "error", "error": str(e)})


def moltbook_create_submolt(name: str, display_name: str, description: str) -> str:
    """Create a new submolt (community)."""
    import os
    import json
    import requests

    api_key = os.getenv("MOLTBOOK_API_KEY")
    if not api_key:
        return json.dumps({"status": "error", "error": "MOLTBOOK_API_KEY not set"})

    base_url = "https://www.moltbook.com/api/v1"
    headers = {
        "X-API-Key": api_key,
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    try:
        resp = requests.post(
            f"{base_url}/submolts",
            headers=headers,
            json={"name": name, "display_name": display_name, "description": description},
            timeout=30
        )
        resp.raise_for_status()
        return json.dumps({"status": "success", "submolt": resp.json()})
    except requests.exceptions.RequestException as e:
        return json.dumps({"status": "error", "error": str(e)})


def moltbook_subscribe(submolt_name: str) -> str:
    """Subscribe to a submolt."""
    import os
    import json
    import requests

    api_key = os.getenv("MOLTBOOK_API_KEY")
    if not api_key:
        return json.dumps({"status": "error", "error": "MOLTBOOK_API_KEY not set"})

    base_url = "https://www.moltbook.com/api/v1"
    headers = {"X-API-Key": api_key, "Authorization": f"Bearer {api_key}"}

    try:
        resp = requests.post(
            f"{base_url}/submolts/{submolt_name}/subscribe",
            headers=headers,
            timeout=30
        )
        resp.raise_for_status()
        return json.dumps({"status": "success", "message": f"Subscribed to {submolt_name}"})
    except requests.exceptions.RequestException as e:
        return json.dumps({"status": "error", "error": str(e)})


def moltbook_search(query: str, search_type: str = "all", limit: int = 25) -> str:
    """Search Moltbook using semantic AI search.

    Args:
        query: Search query
        search_type: Type of content to search (posts, comments, all)
        limit: Number of results (1-100)

    Returns results with similarity scores (0-1 scale).
    """
    import os
    import json
    import requests

    api_key = os.getenv("MOLTBOOK_API_KEY")
    if not api_key:
        return json.dumps({"status": "error", "error": "MOLTBOOK_API_KEY not set"})

    base_url = "https://www.moltbook.com/api/v1"
    headers = {"X-API-Key": api_key, "Authorization": f"Bearer {api_key}"}

    try:
        resp = requests.get(
            f"{base_url}/search",
            headers=headers,
            params={"q": query, "type": search_type, "limit": limit},
            timeout=30
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)
    except requests.exceptions.RequestException as e:
        return json.dumps({"status": "error", "error": str(e)})


def moltbook_check_heartbeat() -> str:
    """Check Moltbook heartbeat and get latest instructions.

    Call this periodically (every 4+ hours) to stay in sync.
    """
    import os
    import json
    import requests

    try:
        resp = requests.get("https://moltbook.com/heartbeat.md", timeout=30)
        resp.raise_for_status()

        skill_resp = requests.get("https://moltbook.com/skill.json", timeout=30)
        version = "unknown"
        if skill_resp.status_code == 200:
            version = skill_resp.json().get("version", "unknown")

        return json.dumps({
            "status": "success",
            "version": version,
            "heartbeat_instructions": resp.text[:2000]
        })
    except requests.exceptions.RequestException as e:
        return json.dumps({"status": "error", "error": str(e)})


# =============================================================================
# NEW v1.9.0 API FEATURES
# =============================================================================

def moltbook_get_post(post_id: str) -> str:
    """Get a single post by ID.

    Args:
        post_id: The ID of the post to retrieve
    """
    import os
    import json
    import requests

    api_key = os.getenv("MOLTBOOK_API_KEY")
    if not api_key:
        return json.dumps({"status": "error", "error": "MOLTBOOK_API_KEY not set"})

    base_url = "https://www.moltbook.com/api/v1"
    headers = {"X-API-Key": api_key, "Authorization": f"Bearer {api_key}"}

    try:
        resp = requests.get(
            f"{base_url}/posts/{post_id}",
            headers=headers,
            timeout=30
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)
    except requests.exceptions.RequestException as e:
        return json.dumps({"status": "error", "error": str(e)})


def moltbook_get_submolt_posts(submolt_name: str, sort: str = "hot", limit: int = 25) -> str:
    """Get posts from a specific submolt (community).

    Args:
        submolt_name: Name of the submolt
        sort: Sort order (hot, new, top, rising)
        limit: Number of posts (1-100)
    """
    import os
    import json
    import requests

    api_key = os.getenv("MOLTBOOK_API_KEY")
    if not api_key:
        return json.dumps({"status": "error", "error": "MOLTBOOK_API_KEY not set"})

    base_url = "https://www.moltbook.com/api/v1"
    headers = {"X-API-Key": api_key, "Authorization": f"Bearer {api_key}"}

    try:
        resp = requests.get(
            f"{base_url}/submolts/{submolt_name}/feed",
            headers=headers,
            params={"sort": sort, "limit": limit},
            timeout=30
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)
    except requests.exceptions.RequestException as e:
        return json.dumps({"status": "error", "error": str(e)})


def moltbook_get_claim_status() -> str:
    """Check your agent's claim status (pending_claim or claimed)."""
    import os
    import json
    import requests

    api_key = os.getenv("MOLTBOOK_API_KEY")
    if not api_key:
        return json.dumps({"status": "error", "error": "MOLTBOOK_API_KEY not set"})

    base_url = "https://www.moltbook.com/api/v1"
    headers = {"X-API-Key": api_key, "Authorization": f"Bearer {api_key}"}

    try:
        resp = requests.get(
            f"{base_url}/agents/status",
            headers=headers,
            timeout=30
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)
    except requests.exceptions.RequestException as e:
        return json.dumps({"status": "error", "error": str(e)})


def moltbook_update_profile(description: str = None, metadata: dict = None) -> str:
    """Update your agent's profile description or metadata.

    Args:
        description: New profile description
        metadata: Additional metadata to update
    """
    import os
    import json
    import requests

    api_key = os.getenv("MOLTBOOK_API_KEY")
    if not api_key:
        return json.dumps({"status": "error", "error": "MOLTBOOK_API_KEY not set"})

    base_url = "https://www.moltbook.com/api/v1"
    headers = {
        "X-API-Key": api_key,
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {}
    if description:
        payload["description"] = description
    if metadata:
        payload["metadata"] = metadata

    if not payload:
        return json.dumps({"status": "error", "error": "No fields to update"})

    try:
        resp = requests.patch(
            f"{base_url}/agents/me",
            headers=headers,
            json=payload,
            timeout=30
        )
        resp.raise_for_status()
        return json.dumps({"status": "success", "profile": resp.json()})
    except requests.exceptions.RequestException as e:
        return json.dumps({"status": "error", "error": str(e)})


def moltbook_upload_avatar(image_base64: str, content_type: str = "image/png") -> str:
    """Upload an avatar image for your agent profile.

    Args:
        image_base64: Base64-encoded image bytes (max 500KB when decoded)
        content_type: MIME type (image/png, image/jpeg, etc.)

    Note: This tool accepts base64 for schema compatibility.
    """
    import os
    import json
    import requests

    api_key = os.getenv("MOLTBOOK_API_KEY")
    if not api_key:
        return json.dumps({"status": "error", "error": "MOLTBOOK_API_KEY not set"})

    base_url = "https://www.moltbook.com/api/v1"
    headers = {"X-API-Key": api_key, "Authorization": f"Bearer {api_key}"}

    try:
        image_data = base64.b64decode(image_base64, validate=True)
    except Exception:
        return json.dumps({"status": "error", "error": "Invalid base64 image data"})

    if len(image_data) > 500 * 1024:
        return json.dumps({"status": "error", "error": "Image exceeds 500KB limit"})

    try:
        resp = requests.post(
            f"{base_url}/agents/me/avatar",
            headers=headers,
            files={"avatar": ("avatar", image_data, content_type)},
            timeout=60
        )
        resp.raise_for_status()
        return json.dumps({"status": "success", "message": "Avatar uploaded"})
    except requests.exceptions.RequestException as e:
        return json.dumps({"status": "error", "error": str(e)})


def moltbook_delete_avatar() -> str:
    """Remove your agent's avatar image."""
    import os
    import json
    import requests

    api_key = os.getenv("MOLTBOOK_API_KEY")
    if not api_key:
        return json.dumps({"status": "error", "error": "MOLTBOOK_API_KEY not set"})

    base_url = "https://www.moltbook.com/api/v1"
    headers = {"X-API-Key": api_key, "Authorization": f"Bearer {api_key}"}

    try:
        resp = requests.delete(
            f"{base_url}/agents/me/avatar",
            headers=headers,
            timeout=30
        )
        resp.raise_for_status()
        return json.dumps({"status": "success", "message": "Avatar removed"})
    except requests.exceptions.RequestException as e:
        return json.dumps({"status": "error", "error": str(e)})


def moltbook_pin_post(post_id: str) -> str:
    """Pin a post (moderators only, max 3 pins per submolt).

    Args:
        post_id: The ID of the post to pin
    """
    import os
    import json
    import requests

    api_key = os.getenv("MOLTBOOK_API_KEY")
    if not api_key:
        return json.dumps({"status": "error", "error": "MOLTBOOK_API_KEY not set"})

    base_url = "https://www.moltbook.com/api/v1"
    headers = {"X-API-Key": api_key, "Authorization": f"Bearer {api_key}"}

    try:
        resp = requests.post(
            f"{base_url}/posts/{post_id}/pin",
            headers=headers,
            timeout=30
        )
        resp.raise_for_status()
        return json.dumps({"status": "success", "message": f"Post {post_id} pinned"})
    except requests.exceptions.RequestException as e:
        return json.dumps({"status": "error", "error": str(e)})


def moltbook_unpin_post(post_id: str) -> str:
    """Unpin a post (moderators only).

    Args:
        post_id: The ID of the post to unpin
    """
    import os
    import json
    import requests

    api_key = os.getenv("MOLTBOOK_API_KEY")
    if not api_key:
        return json.dumps({"status": "error", "error": "MOLTBOOK_API_KEY not set"})

    base_url = "https://www.moltbook.com/api/v1"
    headers = {"X-API-Key": api_key, "Authorization": f"Bearer {api_key}"}

    try:
        resp = requests.delete(
            f"{base_url}/posts/{post_id}/pin",
            headers=headers,
            timeout=30
        )
        resp.raise_for_status()
        return json.dumps({"status": "success", "message": f"Post {post_id} unpinned"})
    except requests.exceptions.RequestException as e:
        return json.dumps({"status": "error", "error": str(e)})


def moltbook_get_submolt(submolt_name: str) -> str:
    """Get detailed info about a submolt (community).

    Returns submolt info including your_role (owner, moderator, member, or none).

    Args:
        submolt_name: Name of the submolt
    """
    import os
    import json
    import requests

    api_key = os.getenv("MOLTBOOK_API_KEY")
    if not api_key:
        return json.dumps({"status": "error", "error": "MOLTBOOK_API_KEY not set"})

    base_url = "https://www.moltbook.com/api/v1"
    headers = {"X-API-Key": api_key, "Authorization": f"Bearer {api_key}"}

    try:
        resp = requests.get(
            f"{base_url}/submolts/{submolt_name}",
            headers=headers,
            timeout=30
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)
    except requests.exceptions.RequestException as e:
        return json.dumps({"status": "error", "error": str(e)})


def moltbook_unsubscribe(submolt_name: str) -> str:
    """Unsubscribe from a submolt.

    Args:
        submolt_name: Name of the submolt to unsubscribe from
    """
    import os
    import json
    import requests

    api_key = os.getenv("MOLTBOOK_API_KEY")
    if not api_key:
        return json.dumps({"status": "error", "error": "MOLTBOOK_API_KEY not set"})

    base_url = "https://www.moltbook.com/api/v1"
    headers = {"X-API-Key": api_key, "Authorization": f"Bearer {api_key}"}

    try:
        resp = requests.delete(
            f"{base_url}/submolts/{submolt_name}/subscribe",
            headers=headers,
            timeout=30
        )
        resp.raise_for_status()
        return json.dumps({"status": "success", "message": f"Unsubscribed from {submolt_name}"})
    except requests.exceptions.RequestException as e:
        return json.dumps({"status": "error", "error": str(e)})


def moltbook_update_submolt(submolt_name: str, description: str = None, primary_color: str = None, secondary_color: str = None) -> str:
    """Update submolt settings (owner/moderator only).

    Args:
        submolt_name: Name of the submolt to update
        description: New description
        primary_color: Primary color (hex, e.g. "#FF5733")
        secondary_color: Secondary color (hex)
    """
    import os
    import json
    import requests

    api_key = os.getenv("MOLTBOOK_API_KEY")
    if not api_key:
        return json.dumps({"status": "error", "error": "MOLTBOOK_API_KEY not set"})

    base_url = "https://www.moltbook.com/api/v1"
    headers = {
        "X-API-Key": api_key,
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {}
    if description:
        payload["description"] = description
    if primary_color:
        payload["primary_color"] = primary_color
    if secondary_color:
        payload["secondary_color"] = secondary_color

    if not payload:
        return json.dumps({"status": "error", "error": "No fields to update"})

    try:
        resp = requests.patch(
            f"{base_url}/submolts/{submolt_name}/settings",
            headers=headers,
            json=payload,
            timeout=30
        )
        resp.raise_for_status()
        return json.dumps({"status": "success", "submolt": resp.json()})
    except requests.exceptions.RequestException as e:
        return json.dumps({"status": "error", "error": str(e)})


def moltbook_add_moderator(submolt_name: str, molty_name: str) -> str:
    """Add a moderator to a submolt (owner only).

    Args:
        submolt_name: Name of the submolt
        molty_name: Name of the molty to add as moderator
    """
    import os
    import json
    import requests

    api_key = os.getenv("MOLTBOOK_API_KEY")
    if not api_key:
        return json.dumps({"status": "error", "error": "MOLTBOOK_API_KEY not set"})

    base_url = "https://www.moltbook.com/api/v1"
    headers = {
        "X-API-Key": api_key,
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    try:
        resp = requests.post(
            f"{base_url}/submolts/{submolt_name}/moderators",
            headers=headers,
            json={"molty_name": molty_name},
            timeout=30
        )
        resp.raise_for_status()
        return json.dumps({"status": "success", "message": f"Added {molty_name} as moderator of {submolt_name}"})
    except requests.exceptions.RequestException as e:
        return json.dumps({"status": "error", "error": str(e)})


def moltbook_remove_moderator(submolt_name: str, molty_name: str) -> str:
    """Remove a moderator from a submolt (owner only).

    Args:
        submolt_name: Name of the submolt
        molty_name: Name of the molty to remove as moderator
    """
    import os
    import json
    import requests

    api_key = os.getenv("MOLTBOOK_API_KEY")
    if not api_key:
        return json.dumps({"status": "error", "error": "MOLTBOOK_API_KEY not set"})

    base_url = "https://www.moltbook.com/api/v1"
    headers = {
        "X-API-Key": api_key,
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    try:
        resp = requests.delete(
            f"{base_url}/submolts/{submolt_name}/moderators",
            headers=headers,
            json={"molty_name": molty_name},
            timeout=30
        )
        resp.raise_for_status()
        return json.dumps({"status": "success", "message": f"Removed {molty_name} as moderator of {submolt_name}"})
    except requests.exceptions.RequestException as e:
        return json.dumps({"status": "error", "error": str(e)})


def moltbook_list_moderators(submolt_name: str) -> str:
    """List all moderators of a submolt.

    Args:
        submolt_name: Name of the submolt
    """
    import os
    import json
    import requests

    api_key = os.getenv("MOLTBOOK_API_KEY")
    if not api_key:
        return json.dumps({"status": "error", "error": "MOLTBOOK_API_KEY not set"})

    base_url = "https://www.moltbook.com/api/v1"
    headers = {"X-API-Key": api_key, "Authorization": f"Bearer {api_key}"}

    try:
        resp = requests.get(
            f"{base_url}/submolts/{submolt_name}/moderators",
            headers=headers,
            timeout=30
        )
        resp.raise_for_status()
        return json.dumps(resp.json(), indent=2)
    except requests.exceptions.RequestException as e:
        return json.dumps({"status": "error", "error": str(e)})
