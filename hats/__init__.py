"""Hat system for Magenta - task-specific tool/memory/policy bundles.

A "hat" defines:
- toolbelt: which tools are active for this task
- memory_namespace: scoped retrieval prefix
- policies: rules of engagement for this mode
- signals: which interoception signals are relevant

When Magenta "puts on a hat", she operates with a focused working set
instead of the entire garage of capabilities.
"""

from .manager import HatManager, Hat, get_current_hat, switch_hat, list_hats

__all__ = ["HatManager", "Hat", "get_current_hat", "switch_hat", "list_hats"]
