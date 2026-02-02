"""Self-dialogue tool for structured internal deliberation.

Uses Letta Conversations API to create internal dialogues with turn limits.
The Conversations API enables parallel execution - the same agent can process
messages in separate conversation contexts without deadlocking.
"""


def self_dialogue(
    initial_prompt: str,
    purpose: str = "deliberation",
    max_turns: int = 3
) -> str:
    """
    Open an internal dialogue with yourself for structured deliberation.
    
    Uses Letta's Conversations API which enables parallel execution of the same
    agent across multiple conversation contexts. The tool blocks waiting for
    responses, but the conversation runs in a separate execution context.
    
    Args:
        initial_prompt: What to deliberate about
        purpose: Type of dialogue (deliberation, critique, exploration, risk_assessment)
        max_turns: Maximum back-and-forth exchanges (1-5, default 3)
    
    Returns:
        Summary of the dialogue including key points and conclusion
    """
    import os
    import uuid
    import json
    from letta_client import Letta
    
    # Validate inputs
    if not initial_prompt or not initial_prompt.strip():
        raise ValueError("initial_prompt is required")
    
    max_turns = min(max(1, max_turns), 5)  # Clamp to 1-5
    
    # Get Letta client config
    api_key = os.getenv("LETTA_API_KEY")
    agent_id = os.getenv("LETTA_AGENT_ID")
    base_url = os.getenv("LETTA_BASE_URL")
    
    if not api_key or not agent_id:
        raise ValueError("LETTA_API_KEY and LETTA_AGENT_ID must be set")
    
    # Initialize client
    try:
        client = Letta(api_key=api_key, base_url=base_url) if base_url else Letta(api_key=api_key)
    except Exception:
        client = Letta()
    
    dialogue_id = uuid.uuid4().hex[:8]
    dialogue_entries = []
    
    # Conclusion phrases to detect when deliberation should end
    conclusion_phrases = [
        "in conclusion", "my conclusion is", "i conclude", "final answer",
        "decision:", "verdict:", "therefore, i will", "therefore, i should", "i've decided"
    ]
    
    # Create a new conversation for the self-dialogue
    # This enables parallel execution - same agent, separate context
    try:
        conv = client.conversations.create(agent_id=agent_id)
        conv_id = conv.id
    except Exception as e:
        return json.dumps({
            "status": "failed",
            "reason": f"Could not create dialogue conversation: {str(e)}",
            "purpose": purpose,
            "initial_prompt": initial_prompt[:200]
        })
    
    try:
        # Send initial prompt with context
        system_context = f"""[SELF-DIALOGUE SESSION: {purpose.upper()}]

You are having a structured internal dialogue to deliberate on a topic.
Purpose: {purpose}
Turn limit: {max_turns} exchanges

Think through this carefully, considering multiple perspectives.
After each response, you'll have a chance to continue or conclude.

TOPIC TO DELIBERATE:
{initial_prompt}"""
        
        # Turn 1: Initial response using Conversations API (parallel execution)
        # The API returns a streaming response that we need to iterate over
        stream = client.conversations.messages.create(
            conversation_id=conv_id,
            messages=[{"role": "user", "content": system_context}]
        )
        
        # Extract assistant messages from the stream
        # Stream contains: ReasoningMessage, AssistantMessage, ToolCallMessage, etc.
        turn_text = ""
        for chunk in stream:
            if getattr(chunk, "message_type", None) == "assistant_message":
                content = getattr(chunk, "content", "") or ""
                if content:
                    turn_text = content  # Take the last assistant message
        
        dialogue_entries.append({"turn": 1, "content": turn_text})
        
        # Continue dialogue for remaining turns
        for turn in range(2, max_turns + 1):
            # Check if should conclude
            should_stop = not turn_text or any(
                phrase in turn_text.lower() for phrase in conclusion_phrases
            )
            if should_stop:
                break
                
            continuation_prompt = f"""[SELF-DIALOGUE TURN {turn}/{max_turns}]

Continue deliberating. Consider:
- What counterarguments exist?
- What am I missing?
- Is there a clear conclusion emerging?

If you've reached a conclusion, explicitly state it."""
            
            # Continue using Conversations API for parallel execution
            stream = client.conversations.messages.create(
                conversation_id=conv_id,
                messages=[{"role": "user", "content": continuation_prompt}]
            )
            
            # Extract assistant messages from stream
            turn_text = ""
            for chunk in stream:
                if getattr(chunk, "message_type", None) == "assistant_message":
                    content = getattr(chunk, "content", "") or ""
                    if content:
                        turn_text = content
            
            dialogue_entries.append({"turn": turn, "content": turn_text})
        
    except Exception as e:
        dialogue_entries.append({"error": str(e)})
    
    finally:
        # Clean up the conversation
        try:
            client.conversations.delete(conv_id)
        except:
            pass
    
    # Build summary
    summary = {
        "status": "completed",
        "purpose": purpose,
        "turns_completed": len(dialogue_entries),
        "max_turns": max_turns,
        "dialogue": dialogue_entries,
        "initial_prompt": initial_prompt[:200]
    }
    
    return json.dumps(summary, indent=2)
