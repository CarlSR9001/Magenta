"""Tool constraints management for rate limiting and validation.

This module provides a centralized system for documenting and enforcing
tool constraints, particularly rate limits that can cause ToolConstraintError.

Usage:
    from tools.tool_constraints import constrained, get_tool_constraints, ToolConstraintError

    @constrained(max_calls_per_response=10)
    def bsky_get_thread(uri: str) -> str:
        ...

    # Or check constraints manually:
    constraints = get_tool_constraints("bsky_get_thread")
"""

import functools
import threading
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Callable, List


class ToolConstraintError(Exception):
    """Raised when a tool constraint is violated.

    This error provides a clear, actionable message to help the caller
    understand what went wrong and how to fix it.
    """

    def __init__(self, tool_name: str, constraint_type: str, message: str,
                 current_count: int = 0, max_allowed: int = 0):
        self.tool_name = tool_name
        self.constraint_type = constraint_type
        self.current_count = current_count
        self.max_allowed = max_allowed
        super().__init__(message)


@dataclass
class ToolConstraint:
    """Describes constraints for a single tool."""

    tool_name: str
    max_calls_per_response: Optional[int] = None
    requires_explicit_query: bool = False
    min_query_length: Optional[int] = None
    max_query_length: Optional[int] = None
    required_params: List[str] = field(default_factory=list)
    param_constraints: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for easy serialization."""
        return {
            "tool_name": self.tool_name,
            "max_calls_per_response": self.max_calls_per_response,
            "requires_explicit_query": self.requires_explicit_query,
            "min_query_length": self.min_query_length,
            "max_query_length": self.max_query_length,
            "required_params": self.required_params,
            "param_constraints": self.param_constraints,
            "description": self.description,
        }


# Registry of all tool constraints
TOOL_CONSTRAINTS: Dict[str, ToolConstraint] = {
    "bsky_get_thread": ToolConstraint(
        tool_name="bsky_get_thread",
        max_calls_per_response=10,
        required_params=["uri"],
        description=(
            "Fetches a Bluesky thread. Limited to 10 calls per response to prevent "
            "API rate limiting and context overflow. If you need more threads, batch "
            "your requests across multiple responses or prioritize the most relevant ones."
        ),
    ),
    "bsky_get_profile": ToolConstraint(
        tool_name="bsky_get_profile",
        max_calls_per_response=15,
        required_params=["actor"],
        description=(
            "Fetches a Bluesky profile. Limited to 15 calls per response. Consider "
            "caching profile information for frequently accessed users."
        ),
    ),
    "bsky_list_notifications": ToolConstraint(
        tool_name="bsky_list_notifications",
        max_calls_per_response=3,
        param_constraints={
            "limit": {"min": 1, "max": 50, "default": 20}
        },
        description=(
            "Lists Bluesky notifications. Limited to 3 calls per response. Use the "
            "limit parameter effectively (max 50) to get sufficient notifications in one call."
        ),
    ),
    "conversation_search": ToolConstraint(
        tool_name="conversation_search",
        max_calls_per_response=5,
        requires_explicit_query=True,
        min_query_length=2,
        max_query_length=500,
        required_params=["query"],
        param_constraints={
            "limit": {"min": 1, "max": 20, "default": 5}
        },
        description=(
            "Searches archival memory. Requires an explicit, non-empty query string. "
            "Limited to 5 calls per response. Be specific with queries to get better results. "
            "Vague or empty queries will be rejected."
        ),
    ),
    "get_author_feed": ToolConstraint(
        tool_name="get_author_feed",
        max_calls_per_response=10,
        required_params=["actor"],
        param_constraints={
            "limit": {"min": 1, "max": 100, "default": 10}
        },
        description=(
            "Gets posts from a user's feed. Limited to 10 calls per response. "
            "Use higher limit values to get more posts in fewer calls."
        ),
    ),
    "self_dialogue": ToolConstraint(
        tool_name="self_dialogue",
        max_calls_per_response=2,
        required_params=["initial_prompt"],
        param_constraints={
            "max_turns": {"min": 1, "max": 5, "default": 3}
        },
        description=(
            "Internal deliberation tool. Limited to 2 calls per response due to "
            "computational cost. Use sparingly for important decisions."
        ),
    ),
    "fetch_webpage": ToolConstraint(
        tool_name="fetch_webpage",
        max_calls_per_response=5,
        required_params=["url"],
        description=(
            "Fetches and parses a webpage. Limited to 5 calls per response to manage "
            "context window usage. Prioritize the most important URLs."
        ),
    ),
    "bsky_telepathy": ToolConstraint(
        tool_name="bsky_telepathy",
        max_calls_per_response=5,
        required_params=["target_handle"],
        description=(
            "Reads another AI agent's cognition data. Limited to 5 calls per response. "
            "Use thoughtfully - this is for understanding other agents' perspectives."
        ),
    ),
}


class CallCounter:
    """Thread-safe call counter for tracking tool invocations within a response.

    Note: The counter should be reset at the start of each new response/context.
    In Letta, this typically happens when a new message is processed.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._counts: Dict[str, int] = {}
                    cls._instance._response_id: Optional[str] = None
        return cls._instance

    def reset(self, response_id: Optional[str] = None) -> None:
        """Reset all counters for a new response."""
        with self._lock:
            self._counts = {}
            self._response_id = response_id

    def increment(self, tool_name: str) -> int:
        """Increment and return the count for a tool."""
        with self._lock:
            self._counts[tool_name] = self._counts.get(tool_name, 0) + 1
            return self._counts[tool_name]

    def get_count(self, tool_name: str) -> int:
        """Get the current count for a tool."""
        with self._lock:
            return self._counts.get(tool_name, 0)

    def get_all_counts(self) -> Dict[str, int]:
        """Get all current counts."""
        with self._lock:
            return dict(self._counts)


# Global counter instance
_call_counter = CallCounter()


def reset_call_counter(response_id: Optional[str] = None) -> None:
    """Reset the call counter for a new response context.

    Call this at the beginning of each new agent response to ensure
    accurate rate limiting within a single response context.
    """
    _call_counter.reset(response_id)


def get_tool_constraints(tool_name: str) -> Optional[ToolConstraint]:
    """Get constraint information for a specific tool.

    Args:
        tool_name: Name of the tool to get constraints for.

    Returns:
        ToolConstraint object if constraints exist, None otherwise.

    Example:
        constraints = get_tool_constraints("bsky_get_thread")
        if constraints:
            print(f"Max calls: {constraints.max_calls_per_response}")
    """
    return TOOL_CONSTRAINTS.get(tool_name)


def get_all_constraints() -> Dict[str, ToolConstraint]:
    """Get all registered tool constraints.

    Returns:
        Dictionary mapping tool names to their ToolConstraint objects.
    """
    return dict(TOOL_CONSTRAINTS)


def format_constraint_error(tool_name: str, constraint: ToolConstraint,
                           current_count: int) -> str:
    """Format a helpful error message for a constraint violation.

    Args:
        tool_name: Name of the tool.
        constraint: The constraint that was violated.
        current_count: How many times the tool was called.

    Returns:
        A clear, actionable error message.
    """
    max_calls = constraint.max_calls_per_response or 0
    return (
        f"Error: {tool_name} can only be called {max_calls} times per response. "
        f"You've called it {current_count} times. "
        f"Consider batching requests or using fewer calls. "
        f"Hint: {constraint.description}"
    )


def validate_params(tool_name: str, **kwargs) -> Optional[str]:
    """Validate parameters against tool constraints.

    Args:
        tool_name: Name of the tool.
        **kwargs: Parameters to validate.

    Returns:
        Error message if validation fails, None if validation passes.
    """
    constraint = TOOL_CONSTRAINTS.get(tool_name)
    if not constraint:
        return None

    # Check required parameters
    for param in constraint.required_params:
        value = kwargs.get(param)
        if value is None or (isinstance(value, str) and not value.strip()):
            return f"Error: {tool_name} requires parameter '{param}'. Please provide a valid value."

    # Check query requirements for search tools
    if constraint.requires_explicit_query:
        query = kwargs.get("query", "")
        if not query or not query.strip():
            return (
                f"Error: {tool_name} requires an explicit search query. "
                "Please provide a specific query string, not an empty or whitespace-only value."
            )
        if constraint.min_query_length and len(query.strip()) < constraint.min_query_length:
            return (
                f"Error: {tool_name} query must be at least {constraint.min_query_length} characters. "
                f"Your query '{query}' is too short. Be more specific."
            )
        if constraint.max_query_length and len(query) > constraint.max_query_length:
            return (
                f"Error: {tool_name} query must be at most {constraint.max_query_length} characters. "
                "Please shorten your query."
            )

    # Check parameter-specific constraints
    for param_name, limits in constraint.param_constraints.items():
        if param_name in kwargs and kwargs[param_name] is not None:
            value = kwargs[param_name]
            if "min" in limits and value < limits["min"]:
                return f"Error: {tool_name} parameter '{param_name}' must be at least {limits['min']}."
            if "max" in limits and value > limits["max"]:
                return f"Error: {tool_name} parameter '{param_name}' must be at most {limits['max']}."

    return None


def check_rate_limit(tool_name: str) -> Optional[str]:
    """Check if calling this tool would exceed rate limits.

    Args:
        tool_name: Name of the tool to check.

    Returns:
        Error message if rate limit would be exceeded, None otherwise.

    Note:
        This does NOT increment the counter. Use increment_and_check for
        atomic check-and-increment operations.
    """
    constraint = TOOL_CONSTRAINTS.get(tool_name)
    if not constraint or not constraint.max_calls_per_response:
        return None

    current = _call_counter.get_count(tool_name)
    if current >= constraint.max_calls_per_response:
        return format_constraint_error(tool_name, constraint, current)

    return None


def increment_and_check(tool_name: str) -> Optional[str]:
    """Increment the call counter and check if limit is exceeded.

    Args:
        tool_name: Name of the tool.

    Returns:
        Error message if rate limit is exceeded, None otherwise.
    """
    constraint = TOOL_CONSTRAINTS.get(tool_name)
    if not constraint or not constraint.max_calls_per_response:
        _call_counter.increment(tool_name)
        return None

    new_count = _call_counter.increment(tool_name)
    if new_count > constraint.max_calls_per_response:
        return format_constraint_error(tool_name, constraint, new_count)

    return None


def constrained(
    max_calls_per_response: Optional[int] = None,
    requires_explicit_query: bool = False,
    required_params: Optional[List[str]] = None,
    validate_before_call: bool = True,
):
    """Decorator to enforce tool constraints.

    This decorator automatically:
    1. Validates required parameters
    2. Checks rate limits before execution
    3. Returns clear error messages on constraint violations

    Args:
        max_calls_per_response: Maximum number of times this tool can be called
            within a single response context.
        requires_explicit_query: If True, the 'query' parameter must be non-empty.
        required_params: List of parameter names that must be provided.
        validate_before_call: If True, validate parameters before calling the function.

    Returns:
        Decorated function that enforces constraints.

    Example:
        @constrained(max_calls_per_response=10, required_params=["uri"])
        def bsky_get_thread(uri: str) -> str:
            ...
    """
    def decorator(func: Callable) -> Callable:
        tool_name = func.__name__

        # Register or update constraint
        if tool_name not in TOOL_CONSTRAINTS:
            TOOL_CONSTRAINTS[tool_name] = ToolConstraint(
                tool_name=tool_name,
                max_calls_per_response=max_calls_per_response,
                requires_explicit_query=requires_explicit_query,
                required_params=required_params or [],
            )
        else:
            # Update existing constraint
            existing = TOOL_CONSTRAINTS[tool_name]
            if max_calls_per_response is not None:
                existing.max_calls_per_response = max_calls_per_response
            if requires_explicit_query:
                existing.requires_explicit_query = requires_explicit_query
            if required_params:
                existing.required_params = required_params

        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> str:
            # Convert args to kwargs for validation
            import inspect
            sig = inspect.signature(func)
            params = list(sig.parameters.keys())
            for i, arg in enumerate(args):
                if i < len(params):
                    kwargs[params[i]] = arg

            # Validate parameters
            if validate_before_call:
                error = validate_params(tool_name, **kwargs)
                if error:
                    return error

            # Check and increment rate limit
            error = increment_and_check(tool_name)
            if error:
                return error

            # Call the actual function
            return func(*args, **kwargs)

        # Add constraint info to docstring
        constraint = TOOL_CONSTRAINTS.get(tool_name)
        if constraint and func.__doc__:
            constraint_doc = f"\n\n    Constraints:\n        - Max calls per response: {constraint.max_calls_per_response or 'unlimited'}"
            if constraint.requires_explicit_query:
                constraint_doc += "\n        - Requires explicit query parameter"
            if constraint.required_params:
                constraint_doc += f"\n        - Required params: {', '.join(constraint.required_params)}"
            wrapper.__doc__ = (func.__doc__ or "") + constraint_doc

        return wrapper
    return decorator


def get_constraints_summary() -> str:
    """Get a human-readable summary of all tool constraints.

    Returns:
        Formatted string describing all constraints.
    """
    lines = ["Tool Constraints Summary", "=" * 50, ""]

    for tool_name, constraint in sorted(TOOL_CONSTRAINTS.items()):
        lines.append(f"## {tool_name}")
        if constraint.max_calls_per_response:
            lines.append(f"   Max calls per response: {constraint.max_calls_per_response}")
        if constraint.requires_explicit_query:
            lines.append("   Requires explicit query: Yes")
        if constraint.required_params:
            lines.append(f"   Required params: {', '.join(constraint.required_params)}")
        if constraint.param_constraints:
            for param, limits in constraint.param_constraints.items():
                limits_str = ", ".join(f"{k}={v}" for k, v in limits.items())
                lines.append(f"   Param '{param}': {limits_str}")
        if constraint.description:
            lines.append(f"   Note: {constraint.description}")
        lines.append("")

    return "\n".join(lines)
