"""Interoception tools for the Magenta agent.

These tools let the agent interact with its own interoception state:
- View current drive pressures
- Set quiet mode
- Record signal outcomes
- Manually adjust pressures

These tools use Letta archival memory to store state, allowing access from
both the local heartbeat process and Letta cloud-based tool execution.
"""

from typing import Optional, Literal
from pydantic import BaseModel, Field

# Marker prefix for interoception state in archival memory
INTEROCEPTION_STATE_MARKER = "[INTEROCEPTION_STATE]"


class InteroceptionStatusArgs(BaseModel):
    """Args for interoception status check."""
    pass  # No args needed


class InteroceptionQuietArgs(BaseModel):
    duration_hours: float = Field(..., ge=0.5, le=24, description="Hours to enable quiet mode")


class InteroceptionSignalArgs(BaseModel):
    signal: Literal[
        "social", "curiosity", "maintenance", "boredom",
        "anxiety", "drift", "stale", "uncanny"
    ] = Field(..., description="Signal type")


class InteroceptionOutcomeArgs(BaseModel):
    signal: Literal[
        "social", "curiosity", "maintenance", "boredom",
        "anxiety", "drift", "stale", "uncanny"
    ] = Field(..., description="Signal type")
    outcome: Literal[
        "high_engagement", "low_engagement", "acknowledged", "error", "skipped"
    ] = Field(..., description="Outcome of acting on the signal")


def _get_letta_client():
    """Get Letta client using environment variables."""
    import os
    from letta_client import Letta

    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")
    base_url = os.getenv("LETTA_BASE_URL")

    if not api_key or not agent_id:
        return None, None, "LETTA_API_KEY and LETTA_AGENT_ID must be set"

    try:
        client = Letta(api_key=api_key, base_url=base_url) if base_url else Letta(api_key=api_key)
        return client, agent_id, None
    except Exception as e:
        return None, None, str(e)


def _init_letta_client(api_key: str, base_url: Optional[str]):
    """Initialize Letta client with compatibility fallbacks."""
    from letta_client import Letta

    if base_url:
        try:
            return Letta(api_key=api_key, base_url=base_url)
        except TypeError:
            try:
                return Letta(key=api_key, base_url=base_url)
            except TypeError:
                return Letta()
    try:
        return Letta(api_key=api_key)
    except TypeError:
        try:
            return Letta(key=api_key)
        except TypeError:
            return Letta()


def _load_interoception_state_from_archival(client, agent_id: str) -> dict:
    """Load interoception state from Letta archival memory."""
    import json

    MARKER = "[INTEROCEPTION_STATE]"

    try:
        # Search for state passage
        passages = client.agents.passages.list(
            agent_id=agent_id,
            search=MARKER,
            limit=10
        )
        items = getattr(passages, "items", passages) if passages else []

        get_ts = lambda passage: getattr(passage, "updated_at", None) or getattr(passage, "created_at", None)

        candidates = [p for p in items if getattr(p, "text", "").startswith(MARKER)]
        if candidates:
            latest = max(candidates, key=lambda p: get_ts(p) or "")
            text = getattr(latest, "text", "")
            json_str = text[len(MARKER):].strip()
            return json.loads(json_str)

        return {}  # No state found
    except Exception:
        return {}


def _save_interoception_state_to_archival(client, agent_id: str, state: dict) -> bool:
    """Save interoception state to Letta archival memory."""
    import json

    MARKER = "[INTEROCEPTION_STATE]"

    try:
        # First, delete any existing state passages
        passages = client.agents.passages.list(
            agent_id=agent_id,
            search=MARKER,
            limit=10
        )
        items = getattr(passages, "items", passages) if passages else []

        for passage in items:
            text = getattr(passage, "text", "")
            if text.startswith(MARKER):
                passage_id = getattr(passage, "id", None)
                if passage_id:
                    # Correct API: delete(memory_id, agent_id=...)
                    client.agents.passages.delete(str(passage_id), agent_id=agent_id)

        # Create new state passage
        state_json = json.dumps(state, indent=2, sort_keys=True)
        client.agents.passages.create(
            agent_id=agent_id,
            text=f"{MARKER}\n{state_json}"
        )
        return True
    except Exception:
        return False


def interoception_get_status() -> str:
    """Get current interoception status - all drive pressures and state.

    Returns the current state of the limbic layer including:
    - Pressure levels for each signal type
    - Quiet mode status
    - Recent emission history
    - Pending items that influence pressure

    Use this to understand your internal drive states.
    """
    import os
    import json
    from letta_client import Letta

    MARKER = "[INTEROCEPTION_STATE]"

    # Get client
    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")
    base_url = os.getenv("LETTA_BASE_URL")

    if not api_key or not agent_id:
        return json.dumps({"error": "LETTA_API_KEY and LETTA_AGENT_ID must be set"})

    try:
        client = _init_letta_client(api_key, base_url)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})

    try:
        # Search for state passage
        passages = client.agents.passages.list(
            agent_id=agent_id,
            search=MARKER,
            limit=5
        )
        items = getattr(passages, "items", passages) if passages else []

        get_ts = lambda passage: getattr(passage, "updated_at", None) or getattr(passage, "created_at", None)

        candidates = [p for p in items if getattr(p, "text", "").startswith(MARKER)]
        state = None
        if candidates:
            latest = max(candidates, key=lambda p: get_ts(p) or "")
            text = getattr(latest, "text", "")
            json_str = text[len(MARKER):].strip()
            state = json.loads(json_str)

        if not state:
            return json.dumps({
                "status": "not_initialized",
                "message": "Interoception state not found in archival memory. The limbic layer may not have synced yet."
            })

        # Format for readability
        quiet_until = state.get("quiet_until")
        quiet_mode = False
        if quiet_until:
            from datetime import datetime, timezone
            try:
                until = datetime.fromisoformat(quiet_until)
                quiet_mode = datetime.now(timezone.utc) < until
            except Exception:
                quiet_mode = False
        summary = {
            "quiet_mode": quiet_mode,
            "quiet_until": quiet_until,
            "total_emissions": state.get("total_emissions", 0),
            "last_wake": state.get("last_wake"),
            "drive_pressures": {},
        }

        pressures = state.get("pressures", {})
        for signal_name, pressure_state in pressures.items():
            summary["drive_pressures"][signal_name] = {
                "pressure": round(pressure_state.get("pressure", 0), 3),
                "pending": pressure_state.get("known_pending", {}),
                "emissions": pressure_state.get("emission_count", 0),
            }

        return json.dumps(summary, indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


def interoception_set_quiet(duration_hours: float) -> str:
    """Enable quiet mode to suppress signals for a duration.

    Quiet mode prevents most signals from firing. Use this when:
    - Human is sleeping
    - You need focused time
    - External circumstances require reduced activity

    The ANXIETY signal can still fire in emergencies even during quiet mode.

    Args:
        duration_hours: How long to enable quiet mode (0.5-24 hours)
    """
    import os
    import json
    from datetime import datetime, timezone, timedelta
    from letta_client import Letta

    MARKER = "[INTEROCEPTION_STATE]"

    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")
    base_url = os.getenv("LETTA_BASE_URL")

    if not api_key or not agent_id:
        return json.dumps({"error": "LETTA_API_KEY and LETTA_AGENT_ID must be set"})

    try:
        client = _init_letta_client(api_key, base_url)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})

    try:
        # Load existing state
        passages = client.agents.passages.list(
            agent_id=agent_id,
            search=MARKER,
            limit=5
        )
        items = getattr(passages, "items", passages) if passages else []

        state = {"pressures": {}}
        old_passage_ids = []
        get_ts = lambda passage: getattr(passage, "updated_at", None) or getattr(passage, "created_at", None)

        candidates = [p for p in items if getattr(p, "text", "").startswith(MARKER)]
        if candidates:
            latest = max(candidates, key=lambda p: get_ts(p) or "")
            text = getattr(latest, "text", "")
            json_str = text[len(MARKER):].strip()
            state = json.loads(json_str)
        for passage in candidates:
            passage_id = getattr(passage, "id", None)
            if passage_id:
                old_passage_ids.append(str(passage_id))

        until = datetime.now(timezone.utc) + timedelta(hours=duration_hours)
        state["quiet_until"] = until.isoformat()

        # Delete any old state passages to avoid stale reads
        for passage_id in old_passage_ids:
            try:
                client.agents.passages.delete(
                    str(passage_id),
                    agent_id=agent_id
                )
            except Exception:
                pass

        # Save updated state
        state_json = json.dumps(state, indent=2, sort_keys=True)
        client.agents.passages.create(
            agent_id=agent_id,
            text=f"{MARKER}\n{state_json}"
        )

        return json.dumps({
            "status": "success",
            "quiet_until": until.isoformat(),
            "message": f"Quiet mode enabled for {duration_hours} hours"
        })
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


def interoception_clear_quiet() -> str:
    """Disable quiet mode immediately.

    Call this to resume normal signal processing before quiet mode expires.
    """
    import os
    import json
    from letta_client import Letta

    MARKER = "[INTEROCEPTION_STATE]"

    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")
    base_url = os.getenv("LETTA_BASE_URL")

    if not api_key or not agent_id:
        return json.dumps({"error": "LETTA_API_KEY and LETTA_AGENT_ID must be set"})

    try:
        client = _init_letta_client(api_key, base_url)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})

    try:
        # Load existing state
        passages = client.agents.passages.list(
            agent_id=agent_id,
            search=MARKER,
            limit=5
        )
        items = getattr(passages, "items", passages) if passages else []

        state = None
        old_passage_ids = []
        get_ts = lambda passage: getattr(passage, "updated_at", None) or getattr(passage, "created_at", None)

        candidates = [p for p in items if getattr(p, "text", "").startswith(MARKER)]
        if candidates:
            latest = max(candidates, key=lambda p: get_ts(p) or "")
            text = getattr(latest, "text", "")
            json_str = text[len(MARKER):].strip()
            state = json.loads(json_str)
        for passage in candidates:
            passage_id = getattr(passage, "id", None)
            if passage_id:
                old_passage_ids.append(str(passage_id))

        if not state:
            return json.dumps({
                "status": "success",
                "message": "Quiet mode was not active"
            })

        state["quiet_until"] = None

        # Delete any old state passages to avoid stale reads
        for passage_id in old_passage_ids:
            try:
                client.agents.passages.delete(
                    str(passage_id),
                    agent_id=agent_id
                )
            except Exception:
                pass

        # Save updated state
        state_json = json.dumps(state, indent=2, sort_keys=True)
        client.agents.passages.create(
            agent_id=agent_id,
            text=f"{MARKER}\n{state_json}"
        )

        return json.dumps({
            "status": "success",
            "message": "Quiet mode disabled"
        })
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


def interoception_boost_signal(signal: str) -> str:
    """Manually boost pressure for a signal.

    Use this when you know a signal should fire soon but pressure
    hasn't built up naturally. For example:
    - Boost SOCIAL when you notice important pending items
    - Boost MAINTENANCE when context feels bloated
    - Boost CURIOSITY when you want to explore

    Args:
        signal: Signal type to boost (social, curiosity, maintenance, etc.)
    """
    import os
    import json
    from datetime import datetime, timezone
    from letta_client import Letta

    MARKER = "[INTEROCEPTION_STATE]"
    valid_signals = {
        "social", "curiosity", "maintenance", "boredom",
        "anxiety", "drift", "stale", "uncanny"
    }

    if hasattr(signal, "value"):
        signal = signal.value
    signal = (signal or "").strip().lower()
    if signal not in valid_signals:
        return json.dumps({
            "status": "error",
            "error": f"Invalid signal. Must be one of: {', '.join(sorted(valid_signals))}"
        })

    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")
    base_url = os.getenv("LETTA_BASE_URL")

    if not api_key or not agent_id:
        return json.dumps({"error": "LETTA_API_KEY and LETTA_AGENT_ID must be set"})

    try:
        client = _init_letta_client(api_key, base_url)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})

    try:
        # Load existing state
        passages = client.agents.passages.list(
            agent_id=agent_id,
            search=MARKER,
            limit=5
        )
        items = getattr(passages, "items", passages) if passages else []

        state = {"pressures": {}}
        old_passage_ids = []
        get_ts = lambda passage: getattr(passage, "updated_at", None) or getattr(passage, "created_at", None)

        candidates = [p for p in items if getattr(p, "text", "").startswith(MARKER)]
        if candidates:
            latest = max(candidates, key=lambda p: get_ts(p) or "")
            text = getattr(latest, "text", "")
            json_str = text[len(MARKER):].strip()
            state = json.loads(json_str)
        for passage in candidates:
            passage_id = getattr(passage, "id", None)
            if passage_id:
                old_passage_ids.append(str(passage_id))

        if "pressures" not in state:
            state["pressures"] = {}
        if signal not in state["pressures"]:
            state["pressures"][signal] = {}

        # Boost pressure by 0.3
        current = state["pressures"][signal].get("pressure", 0)
        new_pressure = min(1.5, current + 0.3)
        state["pressures"][signal]["pressure"] = new_pressure
        state["pressures"][signal]["last_updated"] = datetime.now(timezone.utc).isoformat()

        # Delete any old state passages to avoid stale reads
        for passage_id in old_passage_ids:
            try:
                client.agents.passages.delete(
                    str(passage_id),
                    agent_id=agent_id
                )
            except Exception:
                pass

        # Save updated state
        state_json = json.dumps(state, indent=2, sort_keys=True)
        client.agents.passages.create(
            agent_id=agent_id,
            text=f"{MARKER}\n{state_json}"
        )

        return json.dumps({
            "status": "success",
            "signal": signal,
            "previous_pressure": round(current, 3),
            "new_pressure": round(new_pressure, 3),
            "message": f"Boosted {signal} pressure by 0.3"
        })
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


def interoception_record_outcome(signal: str, outcome: str) -> str:
    """Record the outcome of acting on a signal.

    This helps track which signals lead to productive outcomes.
    Call this after you've responded to a signal.

    Args:
        signal: Signal type that was acted upon
        outcome: Result (high_engagement, low_engagement, acknowledged, error, skipped)
    """
    import os
    import json
    from datetime import datetime, timezone
    from letta_client import Letta

    MARKER = "[INTEROCEPTION_STATE]"
    valid_signals = {
        "social", "curiosity", "maintenance", "boredom",
        "anxiety", "drift", "stale", "uncanny"
    }
    valid_outcomes = {
        "high_engagement", "low_engagement", "acknowledged", "error", "skipped"
    }

    if hasattr(signal, "value"):
        signal = signal.value
    if hasattr(outcome, "value"):
        outcome = outcome.value
    signal = (signal or "").strip().lower()
    outcome = (outcome or "").strip().lower()
    if signal not in valid_signals:
        return json.dumps({
            "status": "error",
            "error": f"Invalid signal. Must be one of: {', '.join(sorted(valid_signals))}"
        })
    if outcome not in valid_outcomes:
        return json.dumps({
            "status": "error",
            "error": f"Invalid outcome. Must be one of: {', '.join(sorted(valid_outcomes))}"
        })

    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")
    base_url = os.getenv("LETTA_BASE_URL")

    if not api_key or not agent_id:
        return json.dumps({"error": "LETTA_API_KEY and LETTA_AGENT_ID must be set"})

    try:
        client = _init_letta_client(api_key, base_url)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})

    try:
        # Load existing state
        passages = client.agents.passages.list(
            agent_id=agent_id,
            search=MARKER,
            limit=5
        )
        items = getattr(passages, "items", passages) if passages else []

        state = {"pressures": {}}
        old_passage_ids = []
        get_ts = lambda passage: getattr(passage, "updated_at", None) or getattr(passage, "created_at", None)

        candidates = [p for p in items if getattr(p, "text", "").startswith(MARKER)]
        if candidates:
            latest = max(candidates, key=lambda p: get_ts(p) or "")
            text = getattr(latest, "text", "")
            json_str = text[len(MARKER):].strip()
            state = json.loads(json_str)
        for passage in candidates:
            passage_id = getattr(passage, "id", None)
            if passage_id:
                old_passage_ids.append(str(passage_id))

        if "pressures" not in state:
            state["pressures"] = {}
        if signal not in state["pressures"]:
            state["pressures"][signal] = {}

        # Record outcome
        if "last_outcomes" not in state["pressures"][signal]:
            state["pressures"][signal]["last_outcomes"] = {}
        state["pressures"][signal]["last_outcomes"][signal] = outcome
        state["pressures"][signal]["last_action"] = datetime.now(timezone.utc).isoformat()

        # Delete any old state passages to avoid stale reads
        for passage_id in old_passage_ids:
            try:
                client.agents.passages.delete(
                    str(passage_id),
                    agent_id=agent_id
                )
            except Exception:
                pass

        # Save updated state
        state_json = json.dumps(state, indent=2, sort_keys=True)
        client.agents.passages.create(
            agent_id=agent_id,
            text=f"{MARKER}\n{state_json}"
        )

        return json.dumps({
            "status": "success",
            "signal": signal,
            "outcome": outcome,
            "message": f"Recorded {outcome} outcome for {signal} signal"
        })
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


def interoception_get_signal_history(signal: str) -> str:
    """Get history for a specific signal.

    Shows emission count, last outcomes, and timing information.

    Args:
        signal: Signal type to get history for
    """
    import os
    import json
    from datetime import datetime, timezone
    from letta_client import Letta

    MARKER = "[INTEROCEPTION_STATE]"
    valid_signals = {
        "social", "curiosity", "maintenance", "boredom",
        "anxiety", "drift", "stale", "uncanny"
    }

    if hasattr(signal, "value"):
        signal = signal.value
    signal = (signal or "").strip().lower()
    if signal not in valid_signals:
        return json.dumps({
            "status": "error",
            "error": f"Invalid signal. Must be one of: {', '.join(sorted(valid_signals))}"
        })

    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")
    base_url = os.getenv("LETTA_BASE_URL")

    if not api_key or not agent_id:
        return json.dumps({"error": "LETTA_API_KEY and LETTA_AGENT_ID must be set"})

    try:
        client = _init_letta_client(api_key, base_url)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})

    try:
        # Load state from archival
        passages = client.agents.passages.list(
            agent_id=agent_id,
            search=MARKER,
            limit=5
        )
        items = getattr(passages, "items", passages) if passages else []

        state = None
        get_ts = lambda passage: getattr(passage, "updated_at", None) or getattr(passage, "created_at", None)

        candidates = [p for p in items if getattr(p, "text", "").startswith(MARKER)]
        state = None
        if candidates:
            latest = max(candidates, key=lambda p: get_ts(p) or "")
            text = getattr(latest, "text", "")
            json_str = text[len(MARKER):].strip()
            state = json.loads(json_str)

        if not state:
            return json.dumps({
                "status": "not_found",
                "message": "No interoception state found in archival memory"
            })

        pressure_state = state.get("pressures", {}).get(signal, {})

        # Calculate time since last emission
        last_emitted = pressure_state.get("last_emitted")
        if last_emitted:
            try:
                then = datetime.fromisoformat(last_emitted)
                now = datetime.now(timezone.utc)
                seconds_ago = (now - then).total_seconds()
                time_since = f"{seconds_ago/3600:.1f} hours ago"
            except Exception:
                time_since = "unknown"
        else:
            time_since = "never"

        return json.dumps({
            "signal": signal,
            "current_pressure": round(pressure_state.get("pressure", 0), 3),
            "emission_count": pressure_state.get("emission_count", 0),
            "last_emitted": last_emitted,
            "time_since_emission": time_since,
            "last_action": pressure_state.get("last_action"),
            "last_outcomes": pressure_state.get("last_outcomes", {}),
            "pending_items": pressure_state.get("known_pending", {}),
        }, indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})
