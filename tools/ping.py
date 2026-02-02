"""Example Letta tool for testing the skeleton."""

from pydantic import BaseModel, Field


class PingArgs(BaseModel):
    message: str = Field(..., description="Message to echo back")


def ping(message: str) -> str:
    return f"pong: {message}"
