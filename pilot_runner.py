#!/usr/bin/env python3
"""Pilot bridge to drive Magenta harness + Letta admin via a local JSONL queue."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from letta_client import Letta

from config_loader import get_config, get_letta_config
from flow import AgentStateStore, OutboxStore, TelemetryStore
from flow.commit import CommitDispatcher
from flow.commit_handlers import (
    commit_block,
    commit_follow,
    commit_like,
    commit_mute,
    commit_post,
    commit_reply,
)
from flow.models import CommitResult, Draft, DraftType, PreflightResult, TelemetryEvent
from flow.preflight import validate_draft
from flow.runner import _apply_commit_state


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8")) or default
    except Exception:
        return default


def _save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _append_output(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True) + "\n")


def _get_letta_client() -> Letta:
    cfg = get_letta_config()
    params = {"api_key": cfg["api_key"], "timeout": cfg["timeout"]}
    if cfg.get("base_url"):
        params["base_url"] = cfg["base_url"]
    try:
        return Letta(**params)
    except TypeError:
        try:
            return Letta(api_key=cfg["api_key"], base_url=cfg.get("base_url")) if cfg.get("base_url") else Letta(api_key=cfg["api_key"])
        except TypeError:
            try:
                return Letta(key=cfg["api_key"], base_url=cfg.get("base_url")) if cfg.get("base_url") else Letta(key=cfg["api_key"])
            except TypeError:
                return Letta()


def _assistant_text(messages) -> str:
    for message in reversed(messages or []):
        if getattr(message, "message_type", None) == "assistant_message":
            return getattr(message, "content", "") or ""
    return ""


def _format_lines(value: str, show_line_numbers: bool = True) -> str:
    if not show_line_numbers:
        return value
    lines = value.split("\n")
    return "\n".join([f"{i:3d}| {line}" for i, line in enumerate(lines, 1)])


def _handle_letta_admin(op: str, args: dict) -> dict:
    client = _get_letta_client()
    cfg = get_letta_config()
    agent_id = cfg["agent_id"]

    if op == "get_recent_messages":
        limit = int(args.get("limit", 20))
        response = client.agents.messages.list(agent_id=agent_id, limit=limit)
        items = getattr(response, "items", response)
        result = []
        for msg in items or []:
            result.append(
                {
                    "origin": "magenta_agent",
                    "message_type": getattr(msg, "message_type", None),
                    "role": getattr(msg, "role", None),
                    "content": getattr(msg, "content", None),
                    "created_at": getattr(msg, "created_at", None),
                }
            )
        return {"messages": result}

    if op == "get_recent_messages_clean":
        limit = int(args.get("limit", 20))
        response = client.agents.messages.list(agent_id=agent_id, limit=limit)
        items = getattr(response, "items", response)
        result = []
        for msg in items or []:
            message_type = getattr(msg, "message_type", None)
            if message_type not in {"assistant_message", "user_message"}:
                continue
            content = getattr(msg, "content", None)
            if not content:
                continue
            result.append(
                {
                    "origin": "magenta_agent",
                    "message_type": message_type,
                    "role": getattr(msg, "role", None),
                    "content": content,
                    "created_at": getattr(msg, "created_at", None),
                }
            )
        return {"messages": result}

    if op == "list_tools":
        agent = client.agents.retrieve(agent_id=agent_id)
        tools = []
        for t in getattr(agent, "tools", []) or []:
            tools.append({"id": t.id, "name": t.name})
        return {"tools": tools}

    if op == "list_passages":
        limit = int(args.get("limit", 20))
        query_text = args.get("query_text")
        if query_text:
            response = client.agents.passages.list(agent_id, query_text=query_text, limit=limit)
        else:
            response = client.agents.passages.list(agent_id, limit=limit)
        items = getattr(response, "items", response)
        passages = []
        for p in items or []:
            passages.append(
                {
                    "id": getattr(p, "id", None),
                    "text": getattr(p, "text", None),
                    "tags": getattr(p, "tags", None),
                }
            )
        return {"passages": passages}

    if op == "create_passage":
        text = args.get("text", "")
        tags = args.get("tags", [])
        created = client.agents.passages.create(agent_id, text=text, tags=tags)
        return {"created": True, "passage_id": getattr(created, "id", None)}

    if op == "delete_passage":
        passage_id = args.get("passage_id")
        if not passage_id:
            return {"error": "missing_passage_id"}
        client.agents.passages.delete(passage_id, agent_id=agent_id)
        return {"deleted": True, "passage_id": passage_id}

    if op == "update_tool_env":
        env = args.get("env", {})
        if hasattr(client.agents, "modify"):
            client.agents.modify(agent_id=agent_id, tool_exec_environment_variables=env)
        else:
            client.agents.update(agent_id=agent_id, tool_exec_environment_variables=env)
        return {"updated": True, "keys": list(env.keys())}

    if op == "send_message":
        content = args.get("content", "")
        if not content:
            return {"error": "missing_content"}
        response = client.agents.messages.create(
            agent_id=agent_id,
            messages=[{"role": "user", "content": content}],
        )
        assistant = _assistant_text(getattr(response, "messages", []))
        return {
            "origin": "magenta_agent",
            "prompt": content,
            "response": assistant,
        }

    if op == "list_blocks":
        include_content = bool(args.get("include_content", False))
        include_slots = bool(args.get("include_slots", False))
        blocks = client.agents.blocks.list(agent_id=agent_id)
        items = getattr(blocks, "items", blocks)
        results = []
        for block in items or []:
            label = getattr(block, "label", None)
            if not label:
                continue
            if not include_slots and label.startswith("ctx_slot_"):
                continue
            value = getattr(block, "value", "") or ""
            info = {
                "label": label,
                "chars": len(value),
                "limit": getattr(block, "limit", 5000),
                "block_id": str(getattr(block, "id", "unknown")),
            }
            if include_content:
                info["content"] = value
            results.append(info)
        return {"blocks": results, "count": len(results)}

    if op == "get_block":
        label = args.get("label")
        if not label:
            return {"error": "missing_label"}
        block = client.agents.blocks.retrieve(agent_id=agent_id, block_label=label)
        value = getattr(block, "value", "") or ""
        return {
            "label": label,
            "block_id": str(getattr(block, "id", "unknown")),
            "chars": len(value),
            "limit": getattr(block, "limit", 5000),
            "content": _format_lines(value, bool(args.get("line_numbers", True))),
        }

    if op == "set_block":
        label = args.get("label")
        value = args.get("value", "")
        if not label:
            return {"error": "missing_label"}
        client.agents.blocks.update(label, agent_id=agent_id, value=value)
        return {"updated": True, "label": label, "chars": len(value)}

    if op == "replace_block_lines":
        label = args.get("label")
        start_line = int(args.get("start_line", 0))
        end_line = int(args.get("end_line", 0))
        new_content = args.get("new_content", "")
        if not label or start_line <= 0 or end_line <= 0:
            return {"error": "missing_label_or_lines"}
        block = client.agents.blocks.retrieve(agent_id=agent_id, block_label=label)
        value = getattr(block, "value", "") or ""
        lines = value.split("\n")
        start_idx = start_line - 1
        end_idx = end_line
        if start_idx >= len(lines) or end_idx > len(lines):
            return {"error": "line_range_out_of_bounds"}
        replacement = new_content.split("\n") if new_content else [""]
        new_lines = lines[:start_idx] + replacement + lines[end_idx:]
        updated = "\n".join(new_lines)
        client.agents.blocks.update(label, agent_id=agent_id, value=updated)
        return {"updated": True, "label": label, "chars": len(updated)}

    if op == "compact_messages":
        pre_limit = int(args.get("pre_limit", 50))
        post_limit = int(args.get("post_limit", 50))
        pre = client.agents.messages.list(agent_id=agent_id, limit=pre_limit)
        client.agents.messages.compact(agent_id=agent_id)
        post = client.agents.messages.list(agent_id=agent_id, limit=post_limit)
        return {
            "compacted": True,
            "pre_count": len(getattr(pre, "items", pre) or []),
            "post_count": len(getattr(post, "items", post) or []),
        }

    return {"error": f"unknown_op:{op}"}


def _build_draft(payload: dict) -> Draft:
    draft_type = DraftType(payload.get("type", "post"))
    return Draft(
        id=payload.get("id") or "",
        type=draft_type,
        target_uri=payload.get("target_uri"),
        text=payload.get("text"),
        intent=payload.get("intent", ""),
        constraints=payload.get("constraints", []),
        confidence=float(payload.get("confidence", 0.0)),
        salience=float(payload.get("salience", 0.0)),
        salience_factors=payload.get("salience_factors", {}),
        risk_flags=payload.get("risk_flags", []),
        abort_if=payload.get("abort_if", []),
        metadata=payload.get("metadata", {}),
    )


def _handle_harness_action(payload: dict) -> dict:
    outbox = OutboxStore(Path("outbox"))
    state_store = AgentStateStore(Path("state/agent_state.json"))
    telemetry = TelemetryStore(Path("state/telemetry.jsonl"))
    state = state_store.load()

    dispatcher = CommitDispatcher(
        {
            DraftType.POST: commit_post,
            DraftType.REPLY: commit_reply,
            DraftType.QUOTE: commit_post,
            DraftType.LIKE: commit_like,
            DraftType.FOLLOW: commit_follow,
            DraftType.MUTE: commit_mute,
            DraftType.BLOCK: commit_block,
        }
    )

    draft_payload = payload.get("draft") or {}
    draft = _build_draft(draft_payload)
    outbox.create(draft)
    mode = payload.get("mode", "queue")
    bypass = bool(payload.get("bypass_preflight", False))

    preflight: Optional[PreflightResult] = None
    commit_result: Optional[CommitResult] = None

    if mode == "queue":
        outbox.mark_queued(draft.id, "pilot_queue")
        telemetry.append(
            TelemetryEvent(
                run_id=payload.get("id", "pilot"),
                loop_iter=0,
                tools_called=["pilot_queue"],
                chosen_action=draft.type.value,
                j_components={},
                salience_components={"S'": draft.salience},
                preflight=None,
                commit_result=None,
                abort_reason="pilot_queued",
            )
        )
        return {"queued": True, "draft_id": draft.id}

    if not bypass:
        preflight = validate_draft(draft, state)
        if not preflight.passed:
            outbox.mark_aborted(draft.id, ";".join(preflight.reasons))
            telemetry.append(
                TelemetryEvent(
                    run_id=payload.get("id", "pilot"),
                    loop_iter=0,
                    tools_called=["pilot_preflight"],
                    chosen_action=draft.type.value,
                    j_components={},
                    salience_components={"S'": draft.salience},
                    preflight=preflight,
                    commit_result=None,
                    abort_reason="pilot_preflight_failed",
                )
            )
            return {"error": "preflight_failed", "reasons": preflight.reasons}

    commit_result = dispatcher.commit(draft)
    if commit_result.success:
        outbox.mark_committed(draft.id, commit_result.external_uri)
        _apply_commit_state(draft, state, state_store, toolset=None, salience=draft.salience)  # toolset unused in helper
    else:
        outbox.mark_aborted(draft.id, commit_result.error or "commit_failed")

    telemetry.append(
        TelemetryEvent(
            run_id=payload.get("id", "pilot"),
            loop_iter=0,
            tools_called=["pilot_commit"],
            chosen_action=draft.type.value,
            j_components={},
            salience_components={"S'": draft.salience},
            preflight=preflight,
            commit_result=commit_result,
            abort_reason=None if commit_result.success else "pilot_commit_failed",
        )
    )
    return {"committed": commit_result.success, "draft_id": draft.id, "external_uri": commit_result.external_uri, "error": commit_result.error}


def process_commands(input_path: Path, output_path: Path, state_path: Path) -> int:
    state = _load_json(state_path, {"offset": 0})
    offset = int(state.get("offset", 0))
    if not input_path.exists():
        return 0
    with input_path.open("r", encoding="utf-8") as handle:
        handle.seek(offset)
        lines = handle.readlines()
        offset = handle.tell()

    processed = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        processed += 1
        try:
            cmd = json.loads(line)
        except json.JSONDecodeError as exc:
            _append_output(output_path, {"ok": False, "error": f"invalid_json:{exc}"})
            continue

        cmd_type = cmd.get("type")
        op = cmd.get("op")
        args = cmd.get("args", {})
        result: dict

        if cmd_type == "letta_admin":
            result = _handle_letta_admin(op, args)
        elif cmd_type == "harness_action":
            result = _handle_harness_action(cmd)
        else:
            result = {"error": "unknown_command_type"}

        _append_output(
            output_path,
            {
                "ok": "error" not in result,
                "id": cmd.get("id"),
                "type": cmd_type,
                "op": op,
                "result": result,
                "ts": _now_iso(),
            },
        )

    state["offset"] = offset
    _save_json(state_path, state)
    return processed


def main() -> None:
    parser = argparse.ArgumentParser(description="Magenta pilot bridge (file queue)")
    parser.add_argument("--input", default="state/pilot_commands.jsonl")
    parser.add_argument("--output", default="state/pilot_outputs.jsonl")
    parser.add_argument("--state", default="state/pilot_state.json")
    parser.add_argument("--follow", action="store_true", help="Continuously watch for new commands")
    parser.add_argument("--interval", type=float, default=2.0, help="Poll interval for follow mode (seconds)")
    args = parser.parse_args()

    get_config("config.yaml")

    input_path = Path(args.input)
    output_path = Path(args.output)
    state_path = Path(args.state)

    if not args.follow:
        process_commands(input_path, output_path, state_path)
        return

    while True:
        process_commands(input_path, output_path, state_path)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
