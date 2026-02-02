"""Simple character counting tool.

LLMs are bad at counting characters. This tool does it accurately.
"""

from pydantic import BaseModel, Field


class CharCountArgs(BaseModel):
    text: str = Field(..., description="Text to count characters in")


def char_count(text: str) -> str:
    """Count characters in text accurately.

    LLMs are notoriously bad at counting characters. Use this tool
    before posting to Bluesky (300 char limit) or anywhere with limits.

    Returns the exact character count and whether it fits common limits.
    """
    import json

    count = len(text)

    return json.dumps({
        "char_count": count,
        "fits_bluesky": count <= 300,
        "fits_tweet": count <= 280,
        "over_by": max(0, count - 300) if count > 300 else None,
        "suggestion": f"Need to cut {count - 300} chars" if count > 300 else "OK"
    })
