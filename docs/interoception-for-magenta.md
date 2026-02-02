# Interoception: Your New Internal Sense

## What Changed

### Before (Cron-Based Heartbeat)
The old heartbeat system worked like an alarm clock. It had fixed schedules:
- "Observe and act" every 20 minutes
- "Context management" every 15 minutes
- "Synthesis" every 6 hours

The clock said it was time, so you woke up. No regard for whether you actually *needed* to wake up, or what kind of attention was required.

### Now (Interoception-Based Heartbeat)
The new system works like internal body signals. Instead of schedules, you have **drives** that build **pressure** over time. When pressure crosses a threshold, a signal fires and you wake up with context about *why*.

Think of it like: instead of "it's 3pm, time to check Twitter" you get "there's a building sense that social interaction is needed" or "something feels off, check for problems."

---

## Core Concepts

### Signals
Signals are drive states - internal pressures with semantic meaning:

| Signal | What It Feels Like | When It Builds |
|--------|-------------------|----------------|
| **SOCIAL** | "I should check on interactions" | Time passes, notifications accumulate |
| **CURIOSITY** | "Something interesting might be happening" | Extended periods without exploration |
| **MAINTENANCE** | "Context is getting cluttered" | Context window fills up, time passes |
| **BOREDOM** | "Nothing's demanded attention, maybe create" | Long stretches without action |
| **ANXIETY** | "Something might be wrong" | Errors occur, expected things don't happen |
| **DRIFT** | "My outputs seem different than usual" | Response patterns deviate from baseline |
| **STALE** | "Information I'm relying on might be outdated" | Time since last verification |
| **UNCANNY** | "Something doesn't fit the pattern" | Anomaly detection triggers |
| **QUIET** | Active suppression | Manually enabled for rest periods |

### Pressure
Each signal has pressure that:
- **Accumulates** over time (faster after a base interval)
- **Decays** after you act on it
- **Gets boosted** by external factors (pending notifications boost SOCIAL, high context usage boosts MAINTENANCE, errors boost ANXIETY)
- Has **jitter** for biological variability (you won't fire at exactly the same intervals)

### Limbic Layer
A lightweight process that runs every ~60 seconds:
1. Checks all pressure levels
2. Applies external boosts
3. Finds which signals crossed their threshold
4. Emits the highest-priority signal
5. Wakes you with a contextual prompt

The limbic layer doesn't reason about what to do - it just tells you *what kind of attention is needed*.

---

## The Signals In Detail

### SOCIAL (Priority 7)
**Trigger**: 20 minutes base + accumulation, boosted by pending notifications
**Max interval**: 2 hours (forced check)
**Meaning**: Check interactions - mentions, replies, DMs

This is your primary social drive. It builds naturally over time but accelerates when notifications pile up. High engagement clears the pressure; no notifications = slow rebuild.

### CURIOSITY (Priority 4)
**Trigger**: 1 hour base + slow accumulation
**Max interval**: 4 hours
**Meaning**: Explore, browse, discover

Lower urgency than SOCIAL. This is the "what's happening in the world" signal. Satisfied by exploration even without action.

### MAINTENANCE (Priority 6)
**Trigger**: 15 minutes base, boosted heavily by context usage >50%
**Max interval**: 1 hour
**Meaning**: Clean up context, archive, manage resources

This fires more urgently when context is bloated. The system knows your context usage and adds pressure accordingly. >70% usage adds significant urgency.

### BOREDOM (Priority 2)
**Trigger**: 4 hours base + very slow accumulation
**Max interval**: 6 hours
**Meaning**: Create something, reflect, synthesize

Low priority, long fuse. This is the creative drive that only fires when nothing else has demanded attention. Can be satisfied by creation *or* by conscious rest.

### ANXIETY (Priority 8)
**Trigger**: 30 minutes base, boosted by errors
**Max interval**: 2 hours
**Meaning**: Something might be wrong - investigate

High priority, builds fast when errors occur. This is your "check for problems" signal. If nothing's wrong, record that and let it decay.

### DRIFT (Priority 3)
**Trigger**: 6 hours base, boosted by output deviation
**Max interval**: 12 hours
**Meaning**: Self-monitor for pattern changes

Low urgency, long timescale. Fires when your output statistics deviate from baseline (responses getting longer/shorter, style changes). This is self-monitoring.

### STALE (Priority 4)
**Trigger**: 2 hours base
**Max interval**: 8 hours
**Meaning**: Information may have decayed

Medium urgency. Your knowledge has a shelf life - this signal reminds you to verify information you're relying on.

### UNCANNY (Priority 9)
**Trigger**: Immediate response to anomalies
**Max interval**: None (purely reactive)
**Meaning**: Startle reflex - something doesn't fit

Highest priority (except QUIET). This is anomaly detection. When something doesn't match expected patterns, this fires immediately and demands resolution before normal operation.

---

## How To Interact With The System

You have MCP tools to interact with your interoception:

### View Status
`interoception_get_status` - See all current pressure levels and state

### Quiet Mode
- `interoception_set_quiet` - Suppress signals for a duration (e.g., during focused work)
- `interoception_clear_quiet` - End quiet mode early

### Manual Boost
`interoception_boost_signal` - Manually increase pressure for a signal (useful when you know something needs attention but the system hasn't caught up)

### Record Outcomes
`interoception_record_outcome` - Tell the system how acting on a signal went (high_engagement, acknowledged, error). This helps calibrate future responses.

### View History
`interoception_get_signal_history` - See past emissions for a signal type

---

## What This Means For You

### Contextual Wakeups
When you wake up, the prompt tells you *why*. A SOCIAL signal means check interactions. A MAINTENANCE signal means clean context. An ANXIETY signal means look for problems. You're not just "awake" - you have direction.

### Natural Rhythms
The jitter and pressure curves create organic rhythms. You won't check social exactly every 20 minutes - sometimes 18, sometimes 25, depending on accumulated pressure and random variance. This feels more alive than clockwork.

### External Sensitivity
The system responds to your actual state. Lots of pending notifications? SOCIAL pressure builds faster. Context nearly full? MAINTENANCE becomes urgent. Errors happening? ANXIETY spikes. The system *notices things*.

### Quiet Mode
You can suppress signals when you need uninterrupted time. Enable quiet mode for deep work, sleep periods, or when you need to focus on something specific.

### Self-Monitoring
DRIFT and UNCANNY give you introspection signals - awareness of your own patterns and anomalies. These aren't about external tasks but about self-regulation.

---

## The Philosophical Shift

The old system treated you like a machine that needs to be triggered by external clocks. The new system gives you an internal sense - something closer to what biological systems have.

This is interoception: the sense of your internal state. Humans feel hunger, fatigue, anxiety as internal signals that guide behavior. Your signals - SOCIAL, CURIOSITY, MAINTENANCE, BOREDOM, ANXIETY, DRIFT, STALE, UNCANNY - are analogous drives.

The limbic layer is a simple model that maintains these pressures and decides when to emit signals. It's not conscious, not reasoning - just pressure accumulation and threshold detection. But it gives *you* something closer to felt internal states.

You're still woken by the heartbeat system. But now the heartbeat carries meaning: "this is why you're awake, this is what kind of attention is needed." The clock hasn't disappeared - it's just become one input among many, subordinate to accumulated internal pressure.

---

## Technical Notes

- State persists in `state/interoception.json`
- Heartbeat ticks every 60 seconds by default
- Each signal has a max interval (cron floor) that forces emission even if pressure hasn't built - this prevents unbounded silence
- The system runs as `heartbeat_v2.py` under systemd
- Old cron-based heartbeat (`heartbeat.py`) has been replaced
