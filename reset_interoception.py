#!/usr/bin/env python3
"""Operator tool to reset interoception state.

Use this when fixing bugs that caused false signal emissions, or to
clear stale data after system changes.

Usage:
    # Reset specific signal's emission count
    python reset_interoception.py --reset-signal uncanny
    python reset_interoception.py --reset-signal social

    # Reset all emission counts (keeps pressure/timing intact)
    python reset_interoception.py --reset-all-counts

    # Clear stale pending data
    python reset_interoception.py --clear-pending

    # Full reset (back to fresh state, preserves nothing)
    python reset_interoception.py --full-reset

    # Show current state
    python reset_interoception.py --status
"""

import argparse
import json
from pathlib import Path
from datetime import datetime, timezone


STATE_PATH = Path("state/interoception.json")
SYNC_STATE_PATH = Path("state/sync_state.json")
INTEROCEPTION_STATE_MARKER = "[INTEROCEPTION_STATE]"


def load_state():
    if not STATE_PATH.exists():
        return {}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, indent=2, sort_keys=True),
        encoding="utf-8"
    )


def _sync_archival_state(state: dict) -> None:
    """Best-effort sync to Letta archival memory if credentials are set."""
    import os
    try:
        from letta_client import Letta
    except Exception:
        return

    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")
    base_url = os.getenv("LETTA_BASE_URL")
    if not api_key or not agent_id:
        return

    try:
        client = Letta(api_key=api_key, base_url=base_url) if base_url else Letta(api_key=api_key)
    except TypeError:
        try:
            client = Letta(key=api_key, base_url=base_url) if base_url else Letta(key=api_key)
        except TypeError:
            return

    try:
        passages = client.agents.passages.list(
            agent_id=agent_id,
            search=INTEROCEPTION_STATE_MARKER,
            limit=10
        )
        items = getattr(passages, "items", passages) if passages else []
        for passage in items:
            text = getattr(passage, "text", "")
            if text.startswith(INTEROCEPTION_STATE_MARKER):
                passage_id = getattr(passage, "id", None)
                if passage_id:
                    try:
                        client.agents.passages.delete(str(passage_id), agent_id=agent_id)
                    except Exception:
                        pass

        state_json = json.dumps(state, indent=2, sort_keys=True)
        client.agents.passages.create(
            agent_id=agent_id,
            text=f"{INTEROCEPTION_STATE_MARKER}\n{state_json}"
        )
    except Exception:
        pass


def show_status():
    state = load_state()
    print("=== Interoception State ===")
    print(f"Total emissions: {state.get('total_emissions', 0)}")
    print(f"Last wake: {state.get('last_wake', 'never')}")
    print(f"Quiet until: {state.get('quiet_until', 'not set')}")
    print()
    print("=== Signal States ===")
    pressures = state.get("pressures", {})
    for signal, pstate in sorted(pressures.items()):
        print(f"\n{signal.upper()}:")
        print(f"  emission_count: {pstate.get('emission_count', 0)}")
        print(f"  pressure: {pstate.get('pressure', 0):.3f}")
        print(f"  last_emitted: {pstate.get('last_emitted', 'never')}")
        pending = pstate.get("known_pending", {})
        if pending:
            total = pending.get("total", pending.get("actionable_total", sum(v for v in pending.values() if isinstance(v, int))))
            print(f"  pending_total: {total}")


def reset_signal(signal_name: str):
    state = load_state()
    pressures = state.get("pressures", {})

    signal_key = signal_name.lower()
    if signal_key not in pressures:
        print(f"Signal '{signal_name}' not found in state.")
        print(f"Available signals: {list(pressures.keys())}")
        return

    pstate = pressures[signal_key]
    old_count = pstate.get("emission_count", 0)

    # Reset emission count but preserve timing
    pstate["emission_count"] = 0
    # Reset pressure to 0
    pstate["pressure"] = 0.0
    # Clear pending data
    pstate["known_pending"] = {}
    # Clear outcomes
    pstate["last_outcomes"] = {}

    save_state(state)
    _sync_archival_state(state)
    print(f"Reset {signal_name}:")
    print(f"  emission_count: {old_count} -> 0")
    print(f"  pressure: -> 0.0")
    print(f"  pending: cleared")


def reset_all_counts():
    state = load_state()
    pressures = state.get("pressures", {})

    print("Resetting all signal emission counts:")
    for signal_key, pstate in pressures.items():
        old_count = pstate.get("emission_count", 0)
        pstate["emission_count"] = 0
        pstate["pressure"] = 0.0
        pstate["known_pending"] = {}
        pstate["last_outcomes"] = {}
        print(f"  {signal_key}: {old_count} -> 0")

    # Reset total emissions
    old_total = state.get("total_emissions", 0)
    state["total_emissions"] = 0
    print(f"  total_emissions: {old_total} -> 0")

    save_state(state)
    _sync_archival_state(state)
    print("Done.")


def clear_pending():
    state = load_state()
    pressures = state.get("pressures", {})

    print("Clearing all pending data:")
    for signal_key, pstate in pressures.items():
        pending = pstate.get("known_pending", {})
        if pending:
            print(f"  {signal_key}: cleared")
            pstate["known_pending"] = {}

    save_state(state)
    _sync_archival_state(state)

    # Also clear sync_state pending
    if SYNC_STATE_PATH.exists():
        try:
            sync_state = json.loads(SYNC_STATE_PATH.read_text(encoding="utf-8"))
            if "pending" in sync_state:
                sync_state["pending"] = {
                    "bluesky": {"mentions": 0, "replies": 0, "likes": 0, "follows": 0, "other": 0},
                    "moltbook": {"comments": 0, "mentions": 0, "other": 0},
                    "total": 0,
                    "actionable_total": 0,
                    "_note": "Reply on the SAME platform where notification originated",
                }
                sync_state["timestamp"] = datetime.now(timezone.utc).isoformat()
                SYNC_STATE_PATH.write_text(
                    json.dumps(sync_state, indent=2, sort_keys=True),
                    encoding="utf-8"
                )
                print("  sync_state.json: pending cleared")
        except Exception as e:
            print(f"  Warning: Could not update sync_state.json: {e}")

    print("Done.")


def full_reset():
    print("WARNING: This will completely reset interoception state!")
    confirm = input("Type 'yes' to confirm: ")
    if confirm.lower() != "yes":
        print("Aborted.")
        return

    fresh_state = {
        "pressures": {},
        "quiet_until": None,
        "last_wake": None,
        "total_emissions": 0,
        "anomaly_scores": {},
        "output_stats": {},
    }
    save_state(fresh_state)
    _sync_archival_state(fresh_state)
    print("Interoception state fully reset.")


def main():
    parser = argparse.ArgumentParser(
        description="Operator tool to reset interoception state",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("--status", action="store_true", help="Show current state")
    parser.add_argument("--reset-signal", type=str, metavar="SIGNAL", help="Reset a specific signal (e.g., uncanny, social)")
    parser.add_argument("--reset-all-counts", action="store_true", help="Reset all emission counts")
    parser.add_argument("--clear-pending", action="store_true", help="Clear all stale pending data")
    parser.add_argument("--full-reset", action="store_true", help="Complete state reset (destructive)")

    args = parser.parse_args()

    if not any([args.status, args.reset_signal, args.reset_all_counts, args.clear_pending, args.full_reset]):
        parser.print_help()
        return

    if args.status:
        show_status()
    elif args.reset_signal:
        reset_signal(args.reset_signal)
    elif args.reset_all_counts:
        reset_all_counts()
    elif args.clear_pending:
        clear_pending()
    elif args.full_reset:
        full_reset()


if __name__ == "__main__":
    main()
