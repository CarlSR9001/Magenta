"""Hat manager - core logic for switching task contexts."""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Where hat definitions live
HATS_DIR = Path(__file__).parent / "definitions"
STATE_FILE = Path("state/current_hat.json")


@dataclass
class Hat:
    """A task-specific operating context."""

    name: str
    description: str

    # Tool allowlist - only these tools are "in the toolbelt"
    toolbelt: List[str] = field(default_factory=list)

    # Memory namespace - prefix for scoped retrieval
    memory_namespace: str = ""

    # Relevant interoception signals for this hat
    relevant_signals: List[str] = field(default_factory=list)

    # Hat-specific policies/rules
    policies: Dict[str, str] = field(default_factory=dict)

    # Platform this hat operates on (for routing)
    platform: Optional[str] = None

    # Whether this hat allows posting/engagement
    allows_engagement: bool = True

    @classmethod
    def from_dict(cls, data: dict) -> "Hat":
        return cls(
            name=data.get("name", "unknown"),
            description=data.get("description", ""),
            toolbelt=data.get("toolbelt", []),
            memory_namespace=data.get("memory_namespace", ""),
            relevant_signals=data.get("relevant_signals", []),
            policies=data.get("policies", {}),
            platform=data.get("platform"),
            allows_engagement=data.get("allows_engagement", True),
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "toolbelt": self.toolbelt,
            "memory_namespace": self.memory_namespace,
            "relevant_signals": self.relevant_signals,
            "policies": self.policies,
            "platform": self.platform,
            "allows_engagement": self.allows_engagement,
        }

    def format_context(self) -> str:
        """Format hat info for injection into agent context."""
        lines = [
            f"## Current Hat: {self.name}",
            f"*{self.description}*",
            "",
            "### Active Toolbelt:",
        ]
        for tool in self.toolbelt[:15]:  # Cap display
            lines.append(f"- {tool}")
        if len(self.toolbelt) > 15:
            lines.append(f"- ... and {len(self.toolbelt) - 15} more")

        if self.policies:
            lines.append("")
            lines.append("### Policies:")
            for key, value in self.policies.items():
                lines.append(f"- **{key}**: {value}")

        if self.platform:
            lines.append("")
            lines.append(f"### Platform: {self.platform}")

        return "\n".join(lines)


class HatManager:
    """Manages hat definitions and switching."""

    def __init__(self, hats_dir: Optional[Path] = None):
        self.hats_dir = hats_dir or HATS_DIR
        self.hats_dir.mkdir(parents=True, exist_ok=True)
        self._hats: Dict[str, Hat] = {}
        self._current_hat: Optional[str] = None
        self._load_hats()
        self._load_state()

    def _load_hats(self) -> None:
        """Load all hat definitions from disk."""
        self._hats = {}
        for path in self.hats_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                hat = Hat.from_dict(data)
                self._hats[hat.name] = hat
                logger.debug(f"Loaded hat: {hat.name}")
            except Exception as e:
                logger.warning(f"Failed to load hat from {path}: {e}")

    def _load_state(self) -> None:
        """Load current hat state."""
        if STATE_FILE.exists():
            try:
                data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
                self._current_hat = data.get("current_hat")
            except Exception:
                self._current_hat = None

    def _save_state(self) -> None:
        """Save current hat state."""
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(
            json.dumps({
                "current_hat": self._current_hat,
                "switched_at": datetime.now(timezone.utc).isoformat(),
            }, indent=2),
            encoding="utf-8"
        )

    def list_hats(self) -> List[Hat]:
        """List all available hats."""
        return list(self._hats.values())

    def get_hat(self, name: str) -> Optional[Hat]:
        """Get a specific hat by name."""
        return self._hats.get(name)

    def get_current_hat(self) -> Optional[Hat]:
        """Get the currently active hat."""
        if self._current_hat:
            return self._hats.get(self._current_hat)
        return None

    def switch_hat(self, name: str) -> Hat:
        """Switch to a different hat."""
        if name not in self._hats:
            raise ValueError(f"Unknown hat: {name}. Available: {list(self._hats.keys())}")

        self._current_hat = name
        self._save_state()
        logger.info(f"Switched to hat: {name}")
        return self._hats[name]

    def clear_hat(self) -> None:
        """Remove current hat (return to default/all tools)."""
        self._current_hat = None
        self._save_state()
        logger.info("Cleared hat - returning to default mode")

    def is_tool_allowed(self, tool_name: str) -> bool:
        """Check if a tool is in the current hat's toolbelt."""
        hat = self.get_current_hat()
        if not hat:
            return True  # No hat = all tools allowed
        if not hat.toolbelt:
            return True  # Empty toolbelt = all tools allowed
        return tool_name in hat.toolbelt

    def get_allowed_tools(self) -> Optional[Set[str]]:
        """Get the set of allowed tools, or None if all allowed."""
        hat = self.get_current_hat()
        if not hat or not hat.toolbelt:
            return None
        return set(hat.toolbelt)

    def get_memory_namespace(self) -> str:
        """Get the current hat's memory namespace prefix."""
        hat = self.get_current_hat()
        if hat and hat.memory_namespace:
            return hat.memory_namespace
        return ""


# Singleton instance
_manager: Optional[HatManager] = None


def _get_manager() -> HatManager:
    global _manager
    if _manager is None:
        _manager = HatManager()
    return _manager


def get_current_hat() -> Optional[Hat]:
    """Get the currently active hat."""
    return _get_manager().get_current_hat()


def switch_hat(name: str) -> Hat:
    """Switch to a different hat."""
    return _get_manager().switch_hat(name)


def list_hats() -> List[Hat]:
    """List all available hats."""
    return _get_manager().list_hats()
