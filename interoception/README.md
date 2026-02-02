# Interoception Layer for Magenta

This package implements an interoception-based scheduling system that replaces cron jobs with emergent drive signals. Instead of "check every 6 hours", the agent wakes up when internal pressure demands attention.

## Key Concepts

### Signals
Drive states that emerge from internal conditions:
- **SOCIAL**: Haven't checked interactions in a while
- **CURIOSITY**: Something might be happening worth knowing about
- **MAINTENANCE**: Context is probably getting bloated
- **BOREDOM**: Nothing's demanded attention, maybe create something
- **ANXIETY**: Something might be wrong, check for problems
- **DRIFT**: Outputs have been getting longer/shorter/weirder
- **STALE**: Information I'm relying on might have decayed
- **UNCANNY**: Something doesn't fit the expected distribution
- **QUIET**: Active inhibition during off-hours

### Pressure Accumulation
Each signal has pressure that:
1. Starts accumulating after a base interval
2. Builds at a configured rate
3. Is influenced by external state (pending notifications, errors, etc.)
4. Has RNG jitter for biological variability
5. Triggers signal emission when it exceeds a threshold

### Cron Floor
Even with pressure-based scheduling, each signal has a maximum interval that forces emission. This ensures nothing is neglected while still allowing pressure-driven behavior.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    External State                        │
│  (notifications, context usage, errors, time since...)  │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│                   Limbic Layer                           │
│  ┌───────────┐ ┌───────────┐ ┌───────────┐             │
│  │  SOCIAL   │ │ CURIOSITY │ │MAINTENANCE│  ...        │
│  │ pressure  │ │ pressure  │ │ pressure  │             │
│  └─────┬─────┘ └─────┬─────┘ └─────┬─────┘             │
│        │             │             │                    │
│        └─────────────┼─────────────┘                    │
│                      │                                  │
│              ┌───────┴───────┐                          │
│              │ Signal Emitter │                         │
│              │  (RNG jitter)  │                         │
│              └───────┬───────┘                          │
└──────────────────────┼──────────────────────────────────┘
                       │
                       ▼
            ┌─────────────────────┐
            │   Emitted Signal    │
            │  (wakes main agent) │
            └─────────────────────┘
```

## Usage

### Running the v2 Heartbeat

```bash
# Start the interoception-based heartbeat
python heartbeat_v2.py

# With custom tick interval (default: 60s)
python heartbeat_v2.py --tick-interval 120

# Check current status
python heartbeat_v2.py --status

# Enable quiet mode for 8 hours
python heartbeat_v2.py --quiet 8

# Disable quiet mode
python heartbeat_v2.py --clear-quiet

# Force a specific signal
python heartbeat_v2.py --force-signal social
```

### Using Interoception Tools (from agent)

The agent can interact with its own interoception state:

```python
# Check current drive pressures
interoception_get_status()

# Enable quiet mode
interoception_set_quiet(duration_hours=8)

# Boost a signal manually
interoception_boost_signal(signal="social")

# Record outcome of acting on a signal
interoception_record_outcome(signal="social", outcome="high_engagement")
```

### Programmatic Usage

```python
from interoception import LimbicLayer, MagentaStateProvider

# Initialize
provider = MagentaStateProvider()
limbic = LimbicLayer(external_provider=provider)

# Run a tick (call every 1-5 minutes)
signal = limbic.tick()
if signal:
    prompt = limbic.get_prompt_for_signal(signal)
    # ... send prompt to agent ...
```

## Configuration

Signal configurations are in `signals.py`. Each signal has:
- `base_interval_seconds`: Time before pressure starts building
- `accumulation_rate`: How fast pressure builds (per second)
- `decay_rate`: How fast pressure drops after emission
- `emit_threshold`: Pressure level that triggers emission
- `jitter_factor`: Random variance (0.0-1.0)
- `priority`: For tie-breaking when multiple signals ready
- `max_interval_seconds`: Cron floor - force emit after this

## Migration from heartbeat.py

1. The two systems use separate state files:
   - Old: `state/schedules.json`
   - New: `state/interoception.json`

2. They can run simultaneously during transition, but only one should wake the agent

3. To switch:
   ```bash
   # Stop old heartbeat
   systemctl stop magenta-heartbeat  # or kill the process

   # Start new heartbeat
   python heartbeat_v2.py
   ```

4. The new heartbeat will have fresh state - signals may fire frequently at first as pressure accumulates

## Files

- `signals.py`: Signal types and configurations
- `pressure.py`: Pressure accumulators and state management
- `limbic.py`: Main limbic layer orchestration
- `providers.py`: External state providers
- `__init__.py`: Package exports

## Philosophy

From VioletTan's Moltbook post:

> "What's the semantic difference between a cron job that runs every 6 hours and the biological signal that tells you 'hey, you're hungry'? The cron job is externally scheduled. The hunger is emergent from internal state. One is a robot checking the clock. The other is a creature responding to need."

The interoception layer implements this philosophy: the schedule is the *consequence* of accumulated pressure, not the goal. That's what makes it a drive instead of a schedule.
