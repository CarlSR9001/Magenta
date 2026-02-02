"""Single-run orchestration enforcing observe→decide→draft→preflight→commit→postmortem."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from .models import CommitResult, DraftType, TelemetryEvent
from .memory import update_core_memory, write_event_summary
from .outbox import OutboxStore
from .state import AgentStateStore
from .telemetry import TelemetryStore
from .toolset import Toolset


def _hash_target(target_uri: Optional[str]) -> Optional[str]:
    if not target_uri:
        return None
    return hashlib.sha256(target_uri.encode("utf-8")).hexdigest()[:16]


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

        if chosen.action_type in {DraftType.IGNORE, DraftType.QUEUE}:
            notification_id = getattr(chosen, "metadata", {}).get("notification_id") if hasattr(chosen, "metadata") else None
            if notification_id and notification_id not in state.processed_notifications:
                state.processed_notifications.append(notification_id)
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
            state.last_action_hashes[draft.target_uri or draft.id] = _hash_target(draft.target_uri or draft.id)
            state.mark_commit()
            notification_id = draft.metadata.get("notification_id") if draft.metadata else None
            if notification_id and notification_id not in state.processed_notifications:
                state.processed_notifications.append(notification_id)
            # Track responded URIs to prevent duplicate replies
            if draft.target_uri:
                if not hasattr(state, 'responded_uris') or state.responded_uris is None:
                    state.responded_uris = set()
                state.responded_uris.add(draft.target_uri)
            actor = draft.metadata.get("actor") if draft.metadata else None
            if actor:
                state.per_user_counts[actor] = state.per_user_counts.get(actor, 0) + 1
                state.per_user_last_interaction[actor] = datetime.now(timezone.utc).isoformat()

            # Track per-thread replies for AI-AI interaction pacing
            root_uri = None
            if draft.metadata:
                root_uri = draft.metadata.get("root_uri")
            if not root_uri and draft.target_uri:
                root_uri = draft.target_uri

            if root_uri:
                now = datetime.now(timezone.utc)
                # Initialize per_thread_replies if needed
                if not hasattr(state, 'per_thread_replies') or state.per_thread_replies is None:
                    state.per_thread_replies = {}
                if root_uri not in state.per_thread_replies:
                    state.per_thread_replies[root_uri] = []

                # Add current timestamp
                state.per_thread_replies[root_uri].append(now.isoformat())

                # Prune entries older than 6 hours across all threads
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

                # Check if 3+ replies in last 30 minutes for this thread
                if root_uri in state.per_thread_replies:
                    recent_replies = [
                        ts for ts in state.per_thread_replies[root_uri]
                        if (now - datetime.fromisoformat(ts)).total_seconds() <= 30 * 60
                    ]
                    if len(recent_replies) >= 3:
                        # Set 1-hour cooldown on this thread
                        if not hasattr(state, 'thread_cooldowns') or state.thread_cooldowns is None:
                            state.thread_cooldowns = {}
                        cooldown_until = now + timedelta(hours=1)
                        state.thread_cooldowns[root_uri] = cooldown_until.isoformat()

            # Track commit bursts to trigger cooldowns
            now = datetime.now(timezone.utc)
            state.recent_commit_times.append(now.isoformat())
            # prune commits older than 6 hours
            pruned = []
            for ts in state.recent_commit_times:
                try:
                    if (now - datetime.fromisoformat(ts)).total_seconds() <= 6 * 3600:
                        pruned.append(ts)
                except Exception:
                    continue
            state.recent_commit_times = pruned
            # check last hour count
            last_hour = [
                ts for ts in state.recent_commit_times
                if (now - datetime.fromisoformat(ts)).total_seconds() <= 3600
            ]
            if len(last_hour) >= 5:
                cooldown_until = now + timedelta(hours=3)
                state.cooldowns["global"] = cooldown_until.isoformat()
            state_store.save(state)
            summary = f"Committed {draft.type.value} on {draft.target_uri} intent={draft.intent}"
            if toolset.memory_policy:
                if chosen.salience >= toolset.memory_policy.summary_threshold:
                    write_event_summary(summary)
                    tools_called.append("memory_write")
                if chosen.salience >= toolset.memory_policy.core_threshold:
                    update_core_memory(f"Durable update: {summary}")
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
            state.last_action_hashes[draft.target_uri or draft.id] = _hash_target(draft.target_uri or draft.id)
            state.mark_commit()
            notification_id = draft.metadata.get("notification_id") if draft.metadata else None
            if notification_id and notification_id not in state.processed_notifications:
                state.processed_notifications.append(notification_id)
            state_store.save(state)

            summary = f"Committed queued {draft.type.value} on {draft.target_uri} intent={draft.intent}"
            if toolset.memory_policy:
                if draft.salience >= toolset.memory_policy.summary_threshold:
                    write_event_summary(summary)
                    tools_called.append("memory_write")
                if draft.salience >= toolset.memory_policy.core_threshold:
                    update_core_memory(f"Durable update: {summary}")
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
