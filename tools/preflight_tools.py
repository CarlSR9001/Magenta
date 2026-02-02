"""Preflight check tool with direct parameters.

Analyzes proposed content before posting - no archival memory lookup.
"""

from typing import Optional, Union, List

try:
    import grapheme
    def count_graphemes(s): return grapheme.length(s)
except ImportError:
    def count_graphemes(s): return len(s)


def preflight_check(
    text: str,
    action_type: str = "reply",
    confidence: float = 0.0,
    risk_flags: Optional[List[str]] = None
) -> str:
    """
    Validate proposed content before posting.

    Call this before any publish action to check guardrails.

    Args:
        text: The text content to validate. For threads, pass a JSON array: '["post1", "post2"]'
        action_type: Type of action (post, reply, quote)
        confidence: Your confidence level (0.0-1.0)
        risk_flags: Optional list of identified risks

    Returns:
        JSON with pass/fail status and reasons
    """
    import json  # Import inside function for Letta sandbox

    # Count graphemes for accurate character limit checking
    # (grapheme library handles emoji/unicode correctly)
    try:
        import grapheme
        grapheme_len = grapheme.length
    except ImportError:
        grapheme_len = len

    reasons = []
    suggested_edits = []
    require_human = False

    risk_flags = risk_flags or []

    # Check confidence threshold
    if confidence < 0.55:
        reasons.append("confidence_below_threshold")

    # Check text requirements - handle JSON array or single string
    texts = []
    if text.strip().startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                texts = parsed
            else:
                texts = [text]
        except json.JSONDecodeError:
            texts = [text]
    else:
        texts = [text]
    if not texts:
        reasons.append("missing_text")
    else:
        for i, post_text in enumerate(texts):
            if not post_text or not str(post_text).strip():
                reasons.append(f"missing_text_post_{i}")
            elif grapheme_len(str(post_text)) > 300:
                reasons.append(f"text_too_long_post_{i}")
                suggested_edits.append(f"shorten_post_{i}")
    
    # Check risk flags
    for risk in {"harassment", "personal_data", "political", "escalation", "high"}:
        if risk in risk_flags:
            require_human = True
            reasons.append(f"risk_flag:{risk}")
    
    passed = len(reasons) == 0 and not require_human
    
    return json.dumps({
        "pass": passed,
        "reasons": reasons,
        "suggested_edits": suggested_edits,
        "require_human": require_human
    })
