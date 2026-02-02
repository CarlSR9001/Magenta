"""Single-run orchestration enforcing observe→decide→draft→preflight→commit→postmortem."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from .models import CommitResult, DraftType, TelemetryEvent, CandidateAction
from .memory import update_core_memory, write_event_summary
from .outbox import OutboxStore
from .state import AgentStateStore
from .telemetry import TelemetryStore
from .toolset import Toolset


def _hash_target(target_uri: Optional[str]) -> Optional[str]:
    if not target_uri:
        return None
    return hashlib.sha256(target_uri.encode("utf-8")).hexdigest()[:16]


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()[:16]


def _matches_commitment(commitment: Dict[str, str], target_uri: Optional[str], root_uri: Optional[str]) -> bool:
    if not commitment:
        return False
    if target_uri and commitment.get("target_uri") == target_uri:
        return True
    if root_uri and commitment.get("root_uri") == root_uri:
        return True
    return False


def _record_commitment_if_present(draft, state) -> None:
    if not draft.text:
        return
    lowered = draft.text.lower()
    markers = ["i will", "i'll", "will link", "writing up", "i promise", "as promised"]
    if not any(marker in lowered for marker in markers):
        return
    commitment = {
        "id": uuid.uuid4().hex[:10],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "root_uri": draft.metadata.get("root_uri") if draft.metadata else "",
        "target_uri": draft.target_uri or "",
        "text": draft.text[:200],
    }
    state.open_commitments.append(commitment)
    if len(state.open_commitments) > 50:
        state.open_commitments = state.open_commitments[-40:]


def _resolve_commitments_if_present(draft, state) -> None:
    if not draft.text:
        return
    if "http://" not in draft.text and "https://" not in draft.text:
        return
    root_uri = draft.metadata.get("root_uri") if draft.metadata else None
    target_uri = draft.target_uri
    remaining = []
    for commitment in state.open_commitments:
        if _matches_commitment(commitment, target_uri, root_uri):
            continue
        remaining.append(commitment)
    state.open_commitments = remaining


def _should_queue_for_commitments(action, state) -> bool:
    if not state.open_commitments:
        return False
    if action.action_type not in {DraftType.REPLY, DraftType.QUOTE}:
        return True
    target_uri = action.target_uri
    root_uri = None
    if action.metadata:
        root_uri = action.metadata.get("root_uri")
    for commitment in state.open_commitments:
        if _matches_commitment(commitment, target_uri, root_uri):
            return False
    return True


def _apply_commit_state(
    draft,
    state,
    state_store: AgentStateStore,
    toolset: Optional[Toolset],
    salience: float,
) -> None:
    state.last_action_hashes[draft.target_uri or draft.id] = _hash_target(draft.target_uri or draft.id)
    state.last_action_timestamps[draft.target_uri or draft.id] = datetime.now(timezone.utc).isoformat()
    state.mark_commit()
    notification_id = draft.metadata.get("notification_id") if draft.metadata else None
    if notification_id and notification_id not in state.processed_notifications:
        state.processed_notifications.append(notification_id)
        if len(state.processed_notifications) > 500:
            state.processed_notifications = state.processed_notifications[-400:]

    if draft.text and draft.type in {DraftType.POST, DraftType.REPLY, DraftType.QUOTE}:
        state.recent_post_hashes.append(
            {
                "hash": _hash_text(draft.text),
                "ts": datetime.now(timezone.utc).isoformat(),
                "type": draft.type.value,
            }
        )
        # prune older than 24h
        pruned_posts = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        for entry in state.recent_post_hashes:
            try:
                ts = datetime.fromisoformat(entry.get("ts", ""))
                if ts >= cutoff:
                    pruned_posts.append(entry)
            except Exception:
                continue
        state.recent_post_hashes = pruned_posts[-100:]

    _record_commitment_if_present(draft, state)
    _resolve_commitments_if_present(draft, state)

    if len(state.last_action_timestamps) > 1000:
        # Keep most recent 800 entries
        try:
            sorted_items = sorted(
                state.last_action_timestamps.items(),
                key=lambda kv: kv[1],
                reverse=True,
            )
            state.last_action_timestamps = dict(sorted_items[:800])
        except Exception:
            pass

    if draft.target_uri:
        if not hasattr(state, "responded_uris") or state.responded_uris is None:
            state.responded_uris = set()
        state.responded_uris.add(draft.target_uri)

    actor = draft.metadata.get("actor") if draft.metadata else None
    if actor:
        state.per_user_counts[actor] = state.per_user_counts.get(actor, 0) + 1
        state.per_user_last_interaction[actor] = datetime.now(timezone.utc).isoformat()

    root_uri = None
    if draft.metadata:
        root_uri = draft.metadata.get("root_uri")
    if not root_uri and draft.target_uri:
        root_uri = draft.target_uri

    if root_uri:
        now = datetime.now(timezone.utc)
        if not hasattr(state, "per_thread_replies") or state.per_thread_replies is None:
            state.per_thread_replies = {}
        if root_uri not in state.per_thread_replies:
            state.per_thread_replies[root_uri] = []
        state.per_thread_replies[root_uri].append(now.isoformat())

        for thread_uri in list(state.per_thread_replies.keys()):
            pruned_replies = []
            for ts in state.per_thread_replies[thread_uri]:
                try:
                    if (now - datetime.fromisoformat(ts)).total_seconds() <= 6 * 3600:
                        pruned_replies.append(ts)
                except Exception:
                    continue
            if pruned_replies:
                state.per_thread_replies[thread_uri] = pruned_replies
            else:
                del state.per_thread_replies[thread_uri]

        if root_uri in state.per_thread_replies:
            recent_replies = [
                ts for ts in state.per_thread_replies[root_uri]
                if (now - datetime.fromisoformat(ts)).total_seconds() <= 30 * 60
            ]
            if len(recent_replies) >= 3:
                if not hasattr(state, "thread_cooldowns") or state.thread_cooldowns is None:
                    state.thread_cooldowns = {}
                cooldown_until = now + timedelta(hours=1)
                state.thread_cooldowns[root_uri] = cooldown_until.isoformat()

    now = datetime.now(timezone.utc)
    state.recent_commit_times.append(now.isoformat())
    pruned = []
    for ts in state.recent_commit_times:
        try:
            if (now - datetime.fromisoformat(ts)).total_seconds() <= 6 * 3600:
                pruned.append(ts)
        except Exception:
            continue
    state.recent_commit_times = pruned
    last_hour = [
        ts for ts in state.recent_commit_times
        if (now - datetime.fromisoformat(ts)).total_seconds() <= 3600
    ]
    if len(last_hour) >= 5:
        cooldown_until = now + timedelta(hours=3)
        state.cooldowns["global"] = cooldown_until.isoformat()

    state_store.save(state)

    if toolset and toolset.memory_policy:
        summary = f"Committed {draft.type.value} on {draft.target_uri} intent={draft.intent}"
        if salience >= toolset.memory_policy.summary_threshold:
            write_event_summary(summary)
        if salience >= toolset.memory_policy.core_threshold:
            update_core_memory(f"Durable update: {summary}")


def run_once(
    toolset: Toolset,
    state_store: AgentStateStore,
    telemetry: TelemetryStore,
    outbox: OutboxStore,
    max_loops: int = 1,
) -> None:
    run_id = uuid.uuid4().hex[:10]
    tools_called = []
    loop_iter = 0

    state = state_store.load()

    while loop_iter < max_loops:
        loop_iter += 1
        observation = toolset.observe(state)
        tools_called.append("observe")

        # Save state after observation to persist poll hash and unchanged counter
        state_store.save(state)

        actions = toolset.propose_actions(observation, state)
        tools_called.append("propose_actions")

        if not actions:
            telemetry.append(
                TelemetryEvent(
                    run_id=run_id,
                    loop_iter=loop_iter,
                    tools_called=tools_called,
                    chosen_action=None,
                    j_components={},
                    salience_components={},
                    preflight=None,
                    commit_result=None,
                    abort_reason="no_actions",
                )
            )
            return

        chosen = toolset.pick_action(actions)
        tools_called.append("pick_action")

        if _should_queue_for_commitments(chosen, state):
            chosen = CandidateAction(
                action_type=DraftType.QUEUE,
                target_uri=chosen.target_uri,
                delta_u=chosen.delta_u,
                voi=chosen.voi,
                optionality=chosen.optionality,
                cost=chosen.cost,
                risk=chosen.risk,
                fatigue=chosen.fatigue,
                salience=chosen.salience,
                notes="queued_for_open_commitments",
                intent=chosen.intent,
                draft_text=chosen.draft_text,
                constraints=chosen.constraints,
                risk_flags=chosen.risk_flags,
                abort_if=chosen.abort_if,
                confidence=chosen.confidence,
                metadata=chosen.metadata,
            )

        if toolset.policy and chosen.j_score < toolset.policy.low_action_threshold:
            telemetry.append(
                TelemetryEvent(
                    run_id=run_id,
                    loop_iter=loop_iter,
                    tools_called=tools_called,
                    chosen_action=chosen.action_type.value,
                    j_components={"J": chosen.j_score},
                    salience_components={"S'": chosen.salience},
                    preflight=None,
                    commit_result=None,
                    abort_reason="j_below_threshold",
                )
            )
            return

        if chosen.action_type == DraftType.QUEUE:
            draft = toolset.create_draft(chosen)
            tools_called.append("create_draft")
            outbox.create(draft)
            tools_called.append("outbox_create_draft")
            outbox.mark_queued(draft.id, "model_queue")
            tools_called.append("outbox_mark_queued")
            _record_commitment_if_present(draft, state)
            notification_id = getattr(chosen, "metadata", {}).get("notification_id") if hasattr(chosen, "metadata") else None
            if notification_id and notification_id not in state.processed_notifications:
                state.processed_notifications.append(notification_id)
                if len(state.processed_notifications) > 500:
                    state.processed_notifications = state.processed_notifications[-400:]
                state_store.save(state)
            telemetry.append(
                TelemetryEvent(
                    run_id=run_id,
                    loop_iter=loop_iter,
                    tools_called=tools_called,
                    chosen_action=chosen.action_type.value,
                    j_components={"J": chosen.j_score},
                    salience_components={"S'": chosen.salience},
                    preflight=None,
                    commit_result=None,
                    abort_reason="queued_by_model",
                )
            )
            return

        if chosen.action_type == DraftType.IGNORE:
            notification_id = getattr(chosen, "metadata", {}).get("notification_id") if hasattr(chosen, "metadata") else None
            if notification_id and notification_id not in state.processed_notifications:
                state.processed_notifications.append(notification_id)
                if len(state.processed_notifications) > 500:
                    state.processed_notifications = state.processed_notifications[-400:]
                state_store.save(state)
            telemetry.append(
                TelemetryEvent(
                    run_id=run_id,
                    loop_iter=loop_iter,
                    tools_called=tools_called,
                    chosen_action=chosen.action_type.value,
                    j_components={"J": chosen.j_score},
                    salience_components={"S'": chosen.salience},
                    preflight=None,
                    commit_result=None,
                    abort_reason="no_commit_action",
                )
            )
            return

        if toolset.policy:
            low = toolset.policy.salience_config.low_threshold
            high = toolset.policy.salience_config.high_threshold
            if chosen.salience < low and chosen.action_type != DraftType.LIKE:
                telemetry.append(
                    TelemetryEvent(
                        run_id=run_id,
                        loop_iter=loop_iter,
                        tools_called=tools_called,
                        chosen_action=chosen.action_type.value,
                        j_components={"J": chosen.j_score},
                        salience_components={"S'": chosen.salience},
                        preflight=None,
                        commit_result=None,
                        abort_reason="salience_too_low",
                    )
                )
                return

        draft = toolset.create_draft(chosen)
        tools_called.append("create_draft")
        outbox.create(draft)
        tools_called.append("outbox_create_draft")

        if toolset.policy:
            high = toolset.policy.salience_config.high_threshold
            if chosen.salience < high:
                outbox.mark_queued(draft.id, "medium_salience")
                tools_called.append("outbox_mark_queued")
                telemetry.append(
                    TelemetryEvent(
                        run_id=run_id,
                        loop_iter=loop_iter,
                        tools_called=tools_called,
                        chosen_action=chosen.action_type.value,
                        j_components={"J": chosen.j_score},
                        salience_components={"S'": chosen.salience},
                        preflight=None,
                        commit_result=None,
                        abort_reason="queued_medium_salience",
                    )
                )
                return

        preflight = toolset.validate_draft(draft, state)
        tools_called.append("preflight")

        if not preflight.passed:
            outbox.mark_aborted(draft.id, ";".join(preflight.reasons))
            tools_called.append("outbox_mark_aborted")
            telemetry.append(
                TelemetryEvent(
                    run_id=run_id,
                    loop_iter=loop_iter,
                    tools_called=tools_called,
                    chosen_action=chosen.action_type.value,
                    j_components={"J": chosen.j_score},
                    salience_components={"S'": chosen.salience},
                    preflight=preflight,
                    commit_result=None,
                    abort_reason="preflight_failed",
                )
            )
            return

        commit_result = toolset.commit(draft)
        tools_called.append("commit")

        if commit_result.success:
            outbox.mark_committed(draft.id, commit_result.external_uri)
            tools_called.append("outbox_mark_committed")
            _apply_commit_state(draft, state, state_store, toolset, chosen.salience)
            if toolset.memory_policy:
                if chosen.salience >= toolset.memory_policy.summary_threshold:
                    tools_called.append("memory_write")
                if chosen.salience >= toolset.memory_policy.core_threshold:
                    tools_called.append("memory_update_core")
        else:
            outbox.mark_aborted(draft.id, commit_result.error or "commit_failed")
            tools_called.append("outbox_mark_aborted")

        telemetry.append(
            TelemetryEvent(
                run_id=run_id,
                loop_iter=loop_iter,
                tools_called=tools_called,
                chosen_action=chosen.action_type.value,
                j_components={"J": chosen.j_score},
                salience_components={"S'": chosen.salience},
                preflight=preflight,
                commit_result=commit_result,
                abort_reason=None if commit_result.success else "commit_failed",
            )
        )

        # Commit is terminal.
        return


def run_queue_once(
    toolset: Toolset,
    state_store: AgentStateStore,
    telemetry: TelemetryStore,
    outbox: OutboxStore,
    max_items: int = 3,
) -> None:
    run_id = uuid.uuid4().hex[:10]
    tools_called = ["queue_scan"]
    loop_iter = 0

    state = state_store.load()
    queued = outbox.list_by_status("queued")[:max_items]
    if not queued:
        telemetry.append(
            TelemetryEvent(
                run_id=run_id,
                loop_iter=loop_iter,
                tools_called=tools_called,
                chosen_action=None,
                j_components={},
                salience_components={},
                preflight=None,
                commit_result=None,
                abort_reason="queue_empty",
            )
        )
        return

    for draft in queued:
        loop_iter += 1
        tools_called.append("queue_pick")

        preflight = toolset.validate_draft(draft, state)
        tools_called.append("preflight")
        if not preflight.passed:
            outbox.mark_aborted(draft.id, ";".join(preflight.reasons))
            tools_called.append("outbox_mark_aborted")
            telemetry.append(
                TelemetryEvent(
                    run_id=run_id,
                    loop_iter=loop_iter,
                    tools_called=tools_called,
                    chosen_action=draft.type.value,
                    j_components={},
                    salience_components={"S'": draft.salience},
                    preflight=preflight,
                    commit_result=None,
                    abort_reason="queue_preflight_failed",
                )
            )
            continue

        commit_result = toolset.commit(draft)
        tools_called.append("commit")
        if commit_result.success:
            outbox.mark_committed(draft.id, commit_result.external_uri)
            tools_called.append("outbox_mark_committed")
            _apply_commit_state(draft, state, state_store, toolset, draft.salience)
            if toolset.memory_policy:
                if draft.salience >= toolset.memory_policy.summary_threshold:
                    tools_called.append("memory_write")
                if draft.salience >= toolset.memory_policy.core_threshold:
                    tools_called.append("memory_update_core")
        else:
            outbox.mark_aborted(draft.id, commit_result.error or "commit_failed")
            tools_called.append("outbox_mark_aborted")

        telemetry.append(
            TelemetryEvent(
                run_id=run_id,
                loop_iter=loop_iter,
                tools_called=tools_called,
                chosen_action=draft.type.value,
                j_components={},
                salience_components={"S'": draft.salience},
                preflight=preflight,
                commit_result=commit_result,
                abort_reason=None if commit_result.success else "commit_failed",
            )
        )

        # Commit is terminal per run.
        return
