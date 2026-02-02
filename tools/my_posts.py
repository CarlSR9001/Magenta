"""Tool to retrieve the agent's own post history."""

from pydantic import BaseModel, Field


class MyPostsArgs(BaseModel):
    limit: int = Field(default=20, ge=1, le=100, description="Number of posts to retrieve")
    include_replies: bool = Field(default=False, description="Include replies in the feed")


def get_my_posts(limit: int = 20, include_replies: bool = False) -> str:
    """
    Get your own recent posts from Bluesky.

    Use this for:
    - Avoiding repetition (don't post similar things you've already said)
    - Following up on your own content (see what got engagement)
    - Maintaining continuity in conversations
    - Reviewing your recent activity

    Args:
        limit: Number of posts to retrieve (default 20, max 100)
        include_replies: If True, include your replies. If False, only original posts.

    Returns:
        YAML-formatted list of your posts with engagement metrics and uri/cid for reference
    """
    import os
    import yaml
    import requests

    username = os.getenv("BSKY_USERNAME")
    password = os.getenv("BSKY_PASSWORD")
    pds_host = os.getenv("PDS_URI", "https://bsky.social")

    if not username or not password:
        return "Error: BSKY_USERNAME and BSKY_PASSWORD must be set"

    try:
        limit = min(max(limit, 1), 100)

        # Create session
        session_url = f"{pds_host}/xrpc/com.atproto.server.createSession"
        session_response = requests.post(
            session_url,
            json={"identifier": username, "password": password},
            timeout=10
        )
        session_response.raise_for_status()
        session = session_response.json()
        access_token = session.get("accessJwt")
        my_handle = session.get("handle")
        my_did = session.get("did")

        if not access_token:
            return "Error: Failed to authenticate"

        # Fetch author feed (using our own handle)
        headers = {"Authorization": f"Bearer {access_token}"}
        feed_url = f"{pds_host}/xrpc/app.bsky.feed.getAuthorFeed"

        params = {
            "actor": my_did,  # Use DID for reliability
            "limit": min(limit * 2, 100),  # Request extra to account for filtered items
        }

        # Filter based on include_replies
        if not include_replies:
            params["filter"] = "posts_no_replies"

        response = requests.get(feed_url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        feed_data = response.json()

        # Format results
        posts = []
        for item in feed_data.get("feed", []):
            post = item.get("post", {})
            record = post.get("record", {})

            # Skip reposts
            if item.get("reason") and item["reason"].get("$type") == "app.bsky.feed.defs#reasonRepost":
                continue

            post_data = {
                "text": record.get("text", ""),
                "created_at": record.get("createdAt", ""),
                "uri": post.get("uri", ""),
                "cid": post.get("cid", ""),
                "likes": post.get("likeCount", 0),
                "reposts": post.get("repostCount", 0),
                "replies": post.get("replyCount", 0),
            }

            # Mark if this is a reply
            if "reply" in record and record["reply"]:
                post_data["is_reply"] = True
                post_data["reply_to_uri"] = record["reply"].get("parent", {}).get("uri", "")

            posts.append(post_data)

            if len(posts) >= limit:
                break

        return yaml.dump({
            "my_posts": {
                "handle": my_handle,
                "did": my_did,
                "count": len(posts),
                "include_replies": include_replies,
                "posts": posts
            }
        }, default_flow_style=False, sort_keys=False)

    except Exception as e:
        return f"Error fetching my posts: {e}"
