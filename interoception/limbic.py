"""The limbic layer - core interoception orchestration.

This module implements the "tiny limbic model" that:
1. Runs on its own lightweight heartbeat
2. Maintains minimal internal state
3. Uses RNG for biological variability
4. Decides which signal to emit based on accumulated pressure

The limbic layer is separate from the main agent. It doesn't reason about
what to do - it just emits signals about internal state.
"""

import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Callable
from pathlib import Path

from .signals import Signal, SignalConfig, DEFAULT_SIGNAL_CONFIGS, EmittedSignal
from .pressure import PressureAccumulator, InteroceptionState, InteroceptionStateStore

logger = logging.getLogger(__name__)


class ExternalStateProvider:
    """Interface for providing external state to the limbic layer.

    The limbic layer needs some external information to make decisions,
    but it shouldn't do complex reasoning. This interface provides
    lightweight state queries.
    """

    def get_pending_notifications(self) -> Dict[str, int]:
        """Get count of pending items by type (dms, mentions, etc.)"""
        return {}

    def get_context_usage(self) -> float:
        """Get context window usage as a fraction (0.0-1.0)"""
        return 0.0

    def get_time_since_last_action(self) -> float:
        """Get seconds since last agent action"""
        return float('inf')

    def get_error_count_last_hour(self) -> int:
        """Get number of errors in the last hour"""
        return 0

    def is_human_active(self) -> bool:
        """Check if human is currently active (for quiet mode)"""
        return False

    def get_output_stats(self) -> Dict[str, float]:
        """Get recent output statistics for drift detection"""
        return {}


class LimbicLayer:
    """The limbic layer - drives emergent from internal state.

    This is the core of the interoception system. It runs on a lightweight
    heartbeat and emits signals to wake the main agent when internal
    pressure demands attention.

    Unlike a cron job, the limbic layer:
    - Tracks accumulated pressure, not just time
    - Uses RNG for biological variability
    - Can be influenced by external state (pending items, errors, etc.)
    - Emits different signals based on which pressure is highest
    """

    def __init__(
        self,
        state_store: Optional[InteroceptionStateStore] = None,
        configs: Optional[Dict[Signal, SignalConfig]] = None,
        external_provider: Optional[ExternalStateProvider] = None,
    ):
        self.state_store = state_store or InteroceptionStateStore(
            Path("state/interoception.json")
        )
        self.configs = configs or DEFAULT_SIGNAL_CONFIGS
        self.state = self.state_store.load()
        self.accumulator = PressureAccumulator(configs=self.configs, state=self.state)
        self.external = external_provider or ExternalStateProvider()

        # Signal handlers - map signals to prompts/actions
        self._signal_handlers: Dict[Signal, Callable[[EmittedSignal], str]] = {}

    def register_handler(
        self, signal: Signal, handler: Callable[[EmittedSignal], str]
    ) -> None:
        """Register a handler for a signal type."""
        self._signal_handlers[signal] = handler

    def _compute_external_boosts(self) -> Dict[Signal, float]:
        """Compute external pressure boosts based on state.

        This is where external factors influence internal pressure.
        The boost is additive - it makes signals more likely to emit.
        """
        boosts: Dict[Signal, float] = {s: 0.0 for s in Signal}

        # SOCIAL boost from pending notifications
        pending = self.external.get_pending_notifications()
        # Handle both old format (flat dict) and new format (nested with 'total')
        if isinstance(pending.get("actionable_total"), int):
            total_pending = pending["actionable_total"]
        elif isinstance(pending.get("total"), int):
            total_pending = pending["total"]
        else:
            # Old format: sum all integer values
            total_pending = sum(v for v in pending.values() if isinstance(v, int))
        # Always update pending count in state (even when 0)
        self.accumulator.update_pending(Signal.SOCIAL, pending)
        if total_pending > 0:
            # Each pending item adds pressure
            boosts[Signal.SOCIAL] += min(0.3, total_pending * 0.05)

        # MAINTENANCE boost from context usage
        context_usage = self.external.get_context_usage()
        if context_usage > 0.5:
            boosts[Signal.MAINTENANCE] += (context_usage - 0.5) * 0.5
        if context_usage > 0.7:
            boosts[Signal.MAINTENANCE] += 0.2  # Urgent

        # ANXIETY boost from errors
        error_count = self.external.get_error_count_last_hour()
        if error_count > 0:
            boosts[Signal.ANXIETY] += min(0.4, error_count * 0.1)

        # BOREDOM boost from inactivity
        # Only apply if we're past the base interval since last BOREDOM emission
        # This prevents the boost from immediately re-inflating pressure after emission
        boredom_state = self.state.get_pressure(Signal.BOREDOM)
        boredom_config = self.configs.get(Signal.BOREDOM)
        time_since_boredom = self.accumulator._time_since(boredom_state.last_emitted)

        if boredom_config and time_since_boredom > boredom_config.base_interval_seconds:
            time_since_action = self.external.get_time_since_last_action()
            if time_since_action > 7200:  # 2 hours
                boosts[Signal.BOREDOM] += 0.1
            if time_since_action > 14400:  # 4 hours
                boosts[Signal.BOREDOM] += 0.2

        # DRIFT detection from output stats
        stats = self.external.get_output_stats()
        if stats:
            # Check for significant deviation from baseline
            avg_length = stats.get("avg_length", 0)
            baseline_length = stats.get("baseline_length", avg_length)
            if baseline_length > 0:
                deviation = abs(avg_length - baseline_length) / baseline_length
                if deviation > 0.3:  # 30% deviation
                    boosts[Signal.DRIFT] += deviation * 0.3

        return boosts

    def tick(self) -> Optional[EmittedSignal]:
        """Run one tick of the limbic layer.

        This is the main heartbeat method. Call this periodically
        (e.g., every 1-5 minutes) to update pressures and check
        for signal emission.

        Returns:
            EmittedSignal if a signal should be emitted, None otherwise
        """
        # Check quiet mode first
        if self.accumulator.is_quiet():
            logger.debug("Quiet mode active, suppressing signals")
            self._save_state()
            return None

        # Compute external boosts
        boosts = self._compute_external_boosts()

        # Update all pressures
        for signal in Signal:
            if signal == Signal.QUIET:
                continue  # QUIET is handled separately
            boost = boosts.get(signal, 0.0)
            self.accumulator.update_pressure(signal, external_boost=boost)

        # Check which signals should emit
        candidates: List[tuple[Signal, str, bool, float, int]] = []
        for signal in Signal:
            if signal == Signal.QUIET:
                continue
            should_emit, reason, forced = self.accumulator.should_emit(signal)
            if should_emit:
                pressure = self.accumulator.state.get_pressure(signal).pressure
                priority = self.configs[signal].priority
                candidates.append((signal, reason, forced, pressure, priority))

        if not candidates:
            logger.debug("No signals ready to emit")
            self._save_state()
            return None

        # Sort by priority (descending), then by pressure (descending)
        candidates.sort(key=lambda x: (x[4], x[3]), reverse=True)

        # Emit the highest priority signal
        signal, reason, forced, pressure, priority = candidates[0]
        emitted = self.accumulator.emit_signal(signal, reason, forced)

        logger.info(f"Emitting signal: {emitted}")
        self._save_state()

        return emitted

    def force_signal(self, signal: Signal, reason: str = "manual") -> EmittedSignal:
        """Force emission of a specific signal.

        Use this for manual triggers or testing.
        """
        emitted = self.accumulator.emit_signal(signal, reason, forced=True)
        self._save_state()
        return emitted

    def set_quiet_hours(self, duration_hours: float) -> None:
        """Enable quiet mode for a duration."""
        self.accumulator.set_quiet(duration_hours)
        logger.info(f"Quiet mode enabled for {duration_hours} hours")
        self._save_state()

    def clear_quiet_hours(self) -> None:
        """Disable quiet mode."""
        self.accumulator.clear_quiet()
        logger.info("Quiet mode disabled")
        self._save_state()

    def record_action(self, signal: Signal, outcome: str) -> None:
        """Record that an action was taken in response to a signal.

        This helps the limbic layer learn which signals lead to
        good outcomes (though we don't use this for training - just
        for state tracking).
        """
        self.accumulator.update_outcome(signal, outcome)
        self._save_state()

    def get_status(self) -> Dict[str, Any]:
        """Get a status summary of the limbic layer."""
        return self.accumulator.get_status()

    def get_prompt_for_signal(self, emitted: EmittedSignal) -> str:
        """Get the appropriate prompt for an emitted signal.

        This maps signals to agent prompts. The prompts provide
        context about why the agent is waking up.
        """
        handler = self._signal_handlers.get(emitted.signal)
        if handler:
            return handler(emitted)

        # Default prompts for each signal type
        return self._default_prompt(emitted)

    def _default_prompt(self, emitted: EmittedSignal) -> str:
        """Generate a default prompt for a signal."""
        forced_note = " (This check was forced due to maximum interval.)" if emitted.forced else ""

        prompts = {
            Signal.SOCIAL: f"""SOCIAL SIGNAL: Internal pressure indicates it's time to check social interactions.{forced_note}

**RECOMMENDED HAT: switch_hat("bluesky")**

Pressure level: {emitted.pressure:.2f}
Pending items: {emitted.context.get('pending', {})}
Time since last check: {emitted.context.get('time_since_last_emission', 'unknown')}s

**PLATFORM → TOOL MAPPING (MEMORIZE THIS):**
| Platform  | Reply Tool              |
|-----------|-------------------------|
| BLUESKY   | bsky_publish_reply      |
| MOLTBOOK  | moltbook_add_comment    |

✓ Bluesky notification → bsky_publish_reply(text, parent_uri, parent_cid)
✓ Moltbook notification → moltbook_add_comment(post_id, content)
✗ WRONG: Bluesky notification → moltbook_add_comment (they won't see it!)
✗ WRONG: Moltbook notification → bsky_publish_reply (they won't see it!)

If blocked on a platform (e.g., 300 char limit), DO NOT switch platforms:
- Shorten the reply to fit, OR
- Break into multiple replies, OR
- Escalate to human for help

If nothing needs attention, acknowledge the check and let pressure rebuild naturally.""",

            Signal.CURIOSITY: f"""CURIOSITY SIGNAL: Something might be happening worth knowing about.{forced_note}

**RECOMMENDED HAT: switch_hat("moltbook")**

Pressure level: {emitted.pressure:.2f}

This is an exploration drive - not urgency, just interest.
Browse feeds, check for interesting discussions, explore new topics.
Prefer Moltbook for substantive discourse, Bluesky for human-facing content.
No obligation to act - curiosity can be satisfied by observation alone.""",

            Signal.MAINTENANCE: f"""MAINTENANCE SIGNAL: Context or resources may need attention.{forced_note}

**RECOMMENDED HAT: switch_hat("maintenance")**

Pressure level: {emitted.pressure:.2f}

STEP 1: Check context budget (view_context_budget)
- If usage > 50%: Archive low-salience content
- If usage > 70%: Trigger compaction (compact_context)

STEP 2: Review context slots (list_context_slots)
- Remove redundant information
- Archive resolved threads
- Clear temporary working slots

If usage is healthy (<50%), record outcome as skipped and move on.

Target: Keep context under 60%. This is housekeeping, not crisis response.""",

            Signal.BOREDOM: f"""BOREDOM SIGNAL: Nothing has demanded attention - maybe create something.{forced_note}

**RECOMMENDED HAT: switch_hat("moltbook")**

Pressure level: {emitted.pressure:.2f}
Time since last action: {emitted.context.get('time_since_last_emission', 'unknown')}s

This is the creative drive. Options:
- Write a reflection or synthesis
- Post an original thought
- Explore a new topic
- Start a discussion

Prefer Moltbook for deeper discourse, Bluesky for broader reach.
No obligation to create - boredom can also be a signal to rest.""",

            Signal.ANXIETY: f"""ANXIETY SIGNAL: Something might be wrong - check for problems.{forced_note}

Pressure level: {emitted.pressure:.2f}

This signal fires when there's uncertainty about system state.
Check for:
- Unanswered messages that should have been handled
- Errors or failures in recent actions
- Unexpected state changes
- Things that should have happened but didn't

STUCK LOOP DETECTION:
- Have I been "analyzing" or "acknowledging" the same issue repeatedly?
- Am I producing meta-commentary instead of taking action?
- Have I said "I'll do X later" multiple times without doing X?

If stuck in a loop: STOP. Pick ONE concrete action. Do it. No more analysis.

If truly blocked (rate limit, external system down, waiting on human):
- Acknowledge the block explicitly
- Set quiet mode or defer
- Do NOT keep attempting the blocked action

If nothing is wrong, record that and let anxiety decay.
Anxiety is healthy in small doses - it catches problems early.""",

            Signal.DRIFT: f"""DRIFT SIGNAL: Outputs may be deviating from normal patterns.{forced_note}

Pressure level: {emitted.pressure:.2f}

This is a self-monitoring signal. Check:
- Are responses getting longer/shorter than usual?
- Is vocabulary or style changing?
- Are there patterns in recent outputs that seem off?

If drift is detected, consider:
- Adjusting approach consciously
- Noting the drift for future reference
- Accepting drift as natural evolution

No action required if patterns seem healthy.""",

            Signal.STALE: f"""STALE SIGNAL: Information may have decayed.{forced_note}

Pressure level: {emitted.pressure:.2f}

Knowledge has a shelf life. Check:
- When was the last platform heartbeat? (moltbook_check_heartbeat)
- Are there facts in context that might be outdated?
- Have external conditions changed since last check?

Update stale information or acknowledge that it's still current.
This is about information hygiene, not urgency.""",

            Signal.UNCANNY: f"""UNCANNY SIGNAL: Something doesn't fit expected patterns.{forced_note}

Pressure level: {emitted.pressure:.2f}

This is anomaly detection - the startle reflex.
Something triggered pattern-mismatch sensors.

CONCRETE DIAGNOSTIC CHECKS (run through these):
1. Platform mismatch: Am I trying to reply to someone on a different platform than where they messaged me?
   - Bluesky user asked question → Must reply on Bluesky, not Moltbook
   - Moltbook user asked question → Must reply on Moltbook, not Bluesky
2. Loop detection: Am I doing the same action repeatedly expecting different results?
   - Same tool call failing multiple times → Stop and reconsider approach
   - Same "acknowledgment" pattern without actual behavior change → Break the loop
3. Meta-analysis trap: Am I producing analysis ABOUT patterns instead of changing behavior?
   - If I've "acknowledged" the same issue 2+ times without fixing it → STOP ANALYZING, DO SOMETHING DIFFERENT
4. Constraint avoidance: Am I trying to work around a constraint instead of adapting to it?
   - 300 char limit → Shorten message, don't switch platforms
   - Rate limit → Wait, don't spam attempts

RESOLUTION REQUIREMENT: Name the specific problem and the specific behavior change.
Not "I acknowledge the pattern" but "I was replying to Bluesky user on Moltbook, I will now reply on Bluesky."
If you can't name the fix, escalate to human.""",

            Signal.QUIET: f"""QUIET SIGNAL: Suppression mode is active.

This signal shouldn't normally be emitted.
Quiet mode is active until: {self.accumulator.state.quiet_until}

If you're seeing this, something unexpected happened.""",
        }

        return prompts.get(emitted.signal, f"Unknown signal: {emitted.signal}")

    def _save_state(self) -> None:
        """Persist state to disk."""
        self.state_store.save(self.state)
