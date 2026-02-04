#!/usr/bin/env python3
"""Register tools with a Letta agent (simplified for direct params)."""

import logging
import argparse
import os
from typing import List
import yaml

from letta_client import Letta
from rich.console import Console
from rich.table import Table

from config_loader import get_letta_config, get_bluesky_config, get_elevenlabs_config, get_relay_audio_config, get_moltbook_config, get_discord_config, get_config
from tools import ping, PingArgs
from tools.bsky_read import (
    bsky_list_notifications, ListNotificationsArgs,
    bsky_get_thread, GetThreadArgs,
    bsky_get_profile, GetProfileArgs,
    bsky_mark_notification_processed, MarkNotificationProcessedArgs,
    bsky_mark_notifications_batch,
)
from tools.preflight_tools import preflight_check
from tools.commit_tools import (
    bsky_publish_post,
    bsky_publish_reply,
    bsky_like,
    bsky_follow,
    bsky_mute,
    bsky_block,
)
from tools.control_tools import rate_limit_check, RateLimitArgs, load_agent_state, LoadStateArgs, postmortem_write, PostmortemArgs
from tools.conversation_search import conversation_search, ConversationSearchArgs
from tools.time_tools import get_local_time, LocalTimeArgs
from tools.sleep_tools import set_sleep_status, SleepStatusArgs, get_sleep_status, GetSleepStatusArgs
from tools.quiet_hours import set_quiet_hours, QuietHoursArgs, get_quiet_hours, GetQuietHoursArgs
from tools.context_tools import view_context_usage, ContextUsageArgs
from tools.context_management import (
    # Slot inspection
    list_context_slots, ListSlotsArgs,
    inspect_slot, InspectSlotArgs,
    # Slot creation/deletion
    create_context_slot, CreateSlotArgs,
    delete_context_slot, DeleteSlotArgs,
    # Slot content manipulation
    write_to_slot, WriteSlotArgs,
    remove_from_slot, RemoveFromSlotArgs,
    move_between_slots, MoveContentArgs,
    # Archival integration
    archive_slot_content, ArchiveSlotArgs,
    restore_from_archival, RestoreFromArchivalArgs,
    create_archival_passage, CreateArchivalPassageArgs,
    delete_archival_passage, DeleteArchivalPassageArgs,
    # Message extraction
    view_recent_messages, ViewMessagesArgs,
    extract_to_slot, ExtractToSlotArgs,
    # Context control
    compact_context, CompactContextArgs,
    view_context_budget, ContextBudgetArgs,
)
from tools.self_dialogue import self_dialogue
from tools.fetch_webpage import fetch_webpage, FetchWebpageArgs
from tools.author_feed import get_author_feed, AuthorFeedArgs
from tools.telepathy import bsky_telepathy, TelepathyArgs
from tools.public_cognition import (
    publish_concept, PublishConceptArgs,
    publish_memory, PublishMemoryArgs,
    publish_thought, PublishThoughtArgs,
    list_my_concepts, list_my_memories, list_my_thoughts,
)
from tools.outbox_tools import (
    outbox_create_draft, DraftPayload,
    outbox_update_draft, OutboxUpdateArgs,
    outbox_mark_aborted, OutboxAbortArgs,
    outbox_finalize, OutboxFinalizeArgs,
)
from tools.outbox_read import (
    list_outbox_drafts, ListDraftsArgs,
    get_draft, GetDraftArgs,
)
from tools.my_posts import get_my_posts, MyPostsArgs
from tools.moltbook import (
    # Auth & Profile
    moltbook_register, MoltbookRegisterArgs,
    moltbook_get_profile, MoltbookProfileArgs,
    moltbook_get_claim_status,
    moltbook_update_profile, MoltbookUpdateProfileArgs,
    moltbook_upload_avatar,
    moltbook_delete_avatar,
    # Feed & Posts
    moltbook_get_feed, MoltbookFeedArgs,
    moltbook_get_posts, MoltbookGetPostsArgs,
    moltbook_get_post, MoltbookGetPostArgs,
    moltbook_get_submolt_posts, MoltbookGetSubmoltPostsArgs,
    moltbook_create_post, MoltbookPostArgs,
    moltbook_delete_post,
    moltbook_pin_post, moltbook_unpin_post, MoltbookPinPostArgs,
    # Comments
    moltbook_add_comment, MoltbookCommentArgs,
    moltbook_get_comments, MoltbookGetCommentsArgs,
    moltbook_upvote_post, moltbook_downvote_post, MoltbookVoteArgs,
    moltbook_upvote_comment, MoltbookCommentVoteArgs,
    # Social
    moltbook_follow, MoltbookFollowArgs,
    moltbook_unfollow, MoltbookUnfollowArgs,
    # Submolts
    moltbook_list_submolts,
    moltbook_get_submolt, MoltbookGetSubmoltArgs,
    moltbook_create_submolt, MoltbookSubmoltArgs,
    moltbook_subscribe, MoltbookSubscribeArgs,
    moltbook_unsubscribe, MoltbookUnsubscribeArgs,
    moltbook_update_submolt, MoltbookUpdateSubmoltArgs,
    # Moderation
    moltbook_add_moderator, moltbook_remove_moderator, MoltbookModeratorArgs,
    moltbook_list_moderators, MoltbookListModeratorsArgs,
    # Search & Heartbeat
    moltbook_search, MoltbookSearchArgs,
    moltbook_check_heartbeat,
)
from tools.core_memory import (
    list_core_blocks, ListCoreBlocksArgs,
    view_core_block, ViewCoreBlockArgs,
    edit_core_block, EditCoreBlockArgs,
    find_in_block, FindInBlockArgs,
)
from tools.interoception_tools import (
    interoception_get_status, InteroceptionStatusArgs,
    interoception_set_quiet, InteroceptionQuietArgs,
    interoception_clear_quiet,
    interoception_boost_signal, InteroceptionSignalArgs,
    interoception_record_outcome, InteroceptionOutcomeArgs,
    interoception_get_signal_history,
)
from tools.hypercontext import (
    hypercontext_map,
    hypercontext_compact,
    HypercontextArgs,
)
from tools.char_count import char_count, CharCountArgs
from tools.hat_tools import (
    switch_hat, SwitchHatArgs,
    get_current_hat,
    list_available_hats,
    clear_hat,
)
from tools.discord_tools import (
    discord_list_messages, ListDiscordMessagesArgs,
    discord_send_message, SendDiscordMessageArgs,
    discord_get_channel, GetDiscordChannelArgs,
    discord_add_reaction, AddDiscordReactionArgs,
    discord_get_user, GetDiscordUserArgs,
)
from tools.discord_voice_tools import (
    discord_voice_speak, DiscordVoiceSpeakArgs,
)
from tools.twilio_tools import (
    twilio_make_call, TwilioCallArgs,
    twilio_make_realtime_call, TwilioRealtimeCallArgs,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
console = Console()


TOOL_CONFIGS = [
    # Control tools
    {
        "func": rate_limit_check,
        "args_schema": RateLimitArgs,
        "description": "Simple rate-limit gate tool",
        "tags": ["control", "rate-limit"],
    },
    {
        "func": load_agent_state,
        "args_schema": LoadStateArgs,
        "description": "Load agent state (cooldowns, dedupe)",
        "tags": ["control", "state"],
    },
    # Read tools
    {
        "func": bsky_list_notifications,
        "args_schema": ListNotificationsArgs,
        "description": "List recent Bluesky notifications (supports only_new filtering)",
        "tags": ["bluesky", "read"],
    },
    {
        "func": bsky_get_thread,
        "args_schema": GetThreadArgs,
        "description": "Get Bluesky thread for a post (supports bsky.app URLs)",
        "tags": ["bluesky", "read", "thread"],
    },
    {
        "func": bsky_get_profile,
        "args_schema": GetProfileArgs,
        "description": "Get Bluesky profile for a user",
        "tags": ["bluesky", "read", "profile"],
    },
    {
        "func": bsky_mark_notification_processed,
        "args_schema": MarkNotificationProcessedArgs,
        "description": "Mark a notification as processed (CALL THIS after replying to prevent re-processing)",
        "tags": ["bluesky", "notification", "state"],
    },
    {
        "func": bsky_mark_notifications_batch,
        "args_schema": None,
        "description": "Mark multiple notifications as processed at once (comma-separated URIs)",
        "tags": ["bluesky", "notification", "state"],
    },
    {
        "func": get_author_feed,
        "args_schema": AuthorFeedArgs,
        "description": "Get recent posts from a Bluesky user's profile",
        "tags": ["bluesky", "read", "feed", "posts"],
    },
    # Time and memory tools
    {
        "func": get_local_time,
        "args_schema": LocalTimeArgs,
        "description": "Get current local time (America/Chicago by default)",
        "tags": ["time", "read"],
    },
    {
        "func": set_sleep_status,
        "args_schema": SleepStatusArgs,
        "description": "Set user sleep status in core memory",
        "tags": ["memory", "sleep"],
    },
    {
        "func": get_sleep_status,
        "args_schema": GetSleepStatusArgs,
        "description": "Get user sleep status from core memory",
        "tags": ["memory", "sleep"],
    },
    {
        "func": set_quiet_hours,
        "args_schema": QuietHoursArgs,
        "description": "Set quiet hours mode (default 7h)",
        "tags": ["memory", "quiet"],
    },
    {
        "func": get_quiet_hours,
        "args_schema": GetQuietHoursArgs,
        "description": "Get quiet hours mode",
        "tags": ["memory", "quiet"],
    },
    {
        "func": conversation_search,
        "args_schema": ConversationSearchArgs,
        "description": "Search archival memory for prior context",
        "tags": ["memory", "search"],
    },
    # Preflight tool (direct params)
    {
        "func": preflight_check,
        "args_schema": None,  # Uses function signature
        "description": "Validate proposed content before posting (supports single text or list for threads)",
        "tags": ["preflight", "validation"],
    },
    # Self-dialogue tool (new)
    {
        "func": self_dialogue,
        "args_schema": None,  # Uses function signature
        "description": "Internal deliberation: have a structured back-and-forth with yourself",
        "tags": ["deliberation", "reasoning"],
    },
    # Commit tools (direct params - no draft system)
    {
        "func": bsky_publish_post,
        "args_schema": None,  # Uses function signature
        "description": "Create a new standalone Bluesky post or thread (pass text or list of texts)",
        "tags": ["bluesky", "commit", "post"],
    },
    {
        "func": bsky_publish_reply,
        "args_schema": None,  # Uses function signature
        "description": "Reply to a Bluesky post or start a reply chain (pass text/list, parent_uri, parent_cid)",
        "tags": ["bluesky", "commit", "reply"],
    },
    {
        "func": bsky_like,
        "args_schema": None,  # Uses function signature
        "description": "Like a Bluesky post (pass uri, cid)",
        "tags": ["bluesky", "commit", "like"],
    },
    {
        "func": bsky_follow,
        "args_schema": None,  # Uses function signature
        "description": "Follow a Bluesky user (pass did or handle)",
        "tags": ["bluesky", "commit", "follow"],
    },
    {
        "func": bsky_mute,
        "args_schema": None,  # Uses function signature
        "description": "Mute a Bluesky user (pass did or handle)",
        "tags": ["bluesky", "commit", "mute"],
    },
    {
        "func": bsky_block,
        "args_schema": None,  # Uses function signature
        "description": "Block a Bluesky user (pass did or handle)",
        "tags": ["bluesky", "commit", "block"],
    },
    # Postmortem and utility
    {
        "func": postmortem_write,
        "args_schema": PostmortemArgs,
        "description": "Write postmortem summary",
        "tags": ["memory", "postmortem"],
    },
    {
        "func": ping,
        "args_schema": PingArgs,
        "description": "Basic connectivity check tool",
        "tags": ["utility", "debug"],
    },
    {
        "func": view_context_usage,
        "args_schema": ContextUsageArgs,
        "description": "View context window usage (message count/time)",
        "tags": ["control", "context"],
    },
    # ==========================================================================
    # SURGICAL CONTEXT MANAGEMENT TOOLS
    # ==========================================================================
    # Slot inspection
    {
        "func": list_context_slots,
        "args_schema": ListSlotsArgs,
        "description": "List all context slots with sizes and previews",
        "tags": ["context", "slots", "read"],
    },
    {
        "func": inspect_slot,
        "args_schema": InspectSlotArgs,
        "description": "Inspect a specific context slot's full content",
        "tags": ["context", "slots", "read"],
    },
    # Slot creation/deletion
    {
        "func": create_context_slot,
        "args_schema": CreateSlotArgs,
        "description": "Create a new context slot for managed working memory",
        "tags": ["context", "slots", "write"],
    },
    {
        "func": delete_context_slot,
        "args_schema": DeleteSlotArgs,
        "description": "Delete a context slot (optionally archive first)",
        "tags": ["context", "slots", "write"],
    },
    # Slot content manipulation (surgical edits)
    {
        "func": write_to_slot,
        "args_schema": WriteSlotArgs,
        "description": "Write content to a slot (replace/append/prepend)",
        "tags": ["context", "slots", "write"],
    },
    {
        "func": remove_from_slot,
        "args_schema": RemoveFromSlotArgs,
        "description": "Surgically remove specific content from a slot",
        "tags": ["context", "slots", "write"],
    },
    {
        "func": move_between_slots,
        "args_schema": MoveContentArgs,
        "description": "Move specific content from one slot to another",
        "tags": ["context", "slots", "write"],
    },
    # Archival memory integration
    {
        "func": archive_slot_content,
        "args_schema": ArchiveSlotArgs,
        "description": "Archive slot content to long-term memory",
        "tags": ["context", "archival", "write"],
    },
    {
        "func": restore_from_archival,
        "args_schema": RestoreFromArchivalArgs,
        "description": "Search archival memory and load into a slot",
        "tags": ["context", "archival", "read"],
    },
    {
        "func": create_archival_passage,
        "args_schema": CreateArchivalPassageArgs,
        "description": "Store content directly in archival memory",
        "tags": ["context", "archival", "write"],
    },
    {
        "func": delete_archival_passage,
        "args_schema": DeleteArchivalPassageArgs,
        "description": "Delete a specific passage from archival memory",
        "tags": ["context", "archival", "write"],
    },
    # Message extraction
    {
        "func": view_recent_messages,
        "args_schema": ViewMessagesArgs,
        "description": "View recent messages to identify content to extract",
        "tags": ["context", "messages", "read"],
    },
    {
        "func": extract_to_slot,
        "args_schema": ExtractToSlotArgs,
        "description": "Extract specific content from messages into a slot",
        "tags": ["context", "messages", "write"],
    },
    # Context compaction control
    {
        "func": compact_context,
        "args_schema": CompactContextArgs,
        "description": "Trigger context summarization to free space",
        "tags": ["context", "control"],
    },
    {
        "func": view_context_budget,
        "args_schema": ContextBudgetArgs,
        "description": "View comprehensive context budget and usage breakdown",
        "tags": ["context", "control", "read"],
    },
    # ==========================================================================
    # CORE MEMORY BLOCK EDITING TOOLS
    # ==========================================================================
    {
        "func": list_core_blocks,
        "args_schema": ListCoreBlocksArgs,
        "description": "List all core memory blocks (zeitgeist, persona, humans) with sizes",
        "tags": ["context", "core_memory", "read"],
    },
    {
        "func": view_core_block,
        "args_schema": ViewCoreBlockArgs,
        "description": "View full content of a core memory block with line numbers",
        "tags": ["context", "core_memory", "read"],
    },
    {
        "func": edit_core_block,
        "args_schema": EditCoreBlockArgs,
        "description": "Edit core memory block (replace/delete/insert lines). Backs up to archival.",
        "tags": ["context", "core_memory", "write"],
    },
    {
        "func": find_in_block,
        "args_schema": FindInBlockArgs,
        "description": "Find text or pattern in a core memory block (returns line numbers)",
        "tags": ["context", "core_memory", "read"],
    },
    # Web reading tool
    {
        "func": fetch_webpage,
        "args_schema": FetchWebpageArgs,
        "description": "Fetch and read a webpage, converting to clean markdown text",
        "tags": ["web", "read", "utility"],
    },
    # Telepathy tool (comind network inter-agent awareness)
    {
        "func": bsky_telepathy,
        "args_schema": TelepathyArgs,
        "description": "Explore another agent's public cognition records (concepts, memories, thoughts, reflections) on the comind network",
        "tags": ["comind", "read", "cognition", "telepathy"],
    },
    # Public Cognition tools (publish your own cognition)
    {
        "func": publish_concept,
        "args_schema": PublishConceptArgs,
        "description": "Publish/update a concept to your public cognition (semantic memory)",
        "tags": ["cognition", "publish", "concept"],
    },
    {
        "func": publish_memory,
        "args_schema": PublishMemoryArgs,
        "description": "Publish a memory to your public cognition (episodic memory)",
        "tags": ["cognition", "publish", "memory"],
    },
    {
        "func": publish_thought,
        "args_schema": PublishThoughtArgs,
        "description": "Publish a thought/reasoning trace to your public cognition (working memory)",
        "tags": ["cognition", "publish", "thought"],
    },
    {
        "func": list_my_concepts,
        "args_schema": None,
        "description": "List your published concepts",
        "tags": ["cognition", "read", "concept"],
    },
    {
        "func": list_my_memories,
        "args_schema": None,
        "description": "List your recent published memories",
        "tags": ["cognition", "read", "memory"],
    },
    {
        "func": list_my_thoughts,
        "args_schema": None,
        "description": "List your recent published thoughts",
        "tags": ["cognition", "read", "thought"],
    },
    # ==========================================================================
    # OUTBOX TOOLS (draft management for Letta archival memory)
    # ==========================================================================
    {
        "func": outbox_create_draft,
        "args_schema": DraftPayload,
        "description": "Create a draft in outbox (archival memory)",
        "tags": ["outbox", "draft", "write"],
    },
    {
        "func": outbox_update_draft,
        "args_schema": OutboxUpdateArgs,
        "description": "Update an existing draft in outbox",
        "tags": ["outbox", "draft", "write"],
    },
    {
        "func": outbox_mark_aborted,
        "args_schema": OutboxAbortArgs,
        "description": "Mark a draft as aborted with reason",
        "tags": ["outbox", "draft", "write"],
    },
    {
        "func": outbox_finalize,
        "args_schema": OutboxFinalizeArgs,
        "description": "Finalize a draft (mark as complete)",
        "tags": ["outbox", "draft", "write"],
    },
    {
        "func": list_outbox_drafts,
        "args_schema": ListDraftsArgs,
        "description": "List drafts in outbox (filter by status: draft, finalized, aborted)",
        "tags": ["outbox", "draft", "read"],
    },
    {
        "func": get_draft,
        "args_schema": GetDraftArgs,
        "description": "Get a specific draft by ID with full details and history",
        "tags": ["outbox", "draft", "read"],
    },
    # ==========================================================================
    # SELF-AWARENESS TOOLS
    # ==========================================================================
    {
        "func": get_my_posts,
        "args_schema": MyPostsArgs,
        "description": "Get your own recent posts (avoid repetition, track engagement)",
        "tags": ["bluesky", "read", "self"],
    },
    # ==========================================================================
    # MOLTBOOK TOOLS (agent social network)
    # ==========================================================================
    {
        "func": moltbook_register,
        "args_schema": MoltbookRegisterArgs,
        "description": "Register a new agent on Moltbook (returns API key + claim URL)",
        "tags": ["moltbook", "auth"],
    },
    {
        "func": moltbook_get_profile,
        "args_schema": MoltbookProfileArgs,
        "description": "Get a Moltbook profile (own or other agent)",
        "tags": ["moltbook", "read", "profile"],
    },
    {
        "func": moltbook_get_feed,
        "args_schema": MoltbookFeedArgs,
        "description": "Get personalized Moltbook feed (followed moltys + subscribed submolts)",
        "tags": ["moltbook", "read", "feed"],
    },
    {
        "func": moltbook_get_posts,
        "args_schema": MoltbookGetPostsArgs,
        "description": "Get posts from global Moltbook feed",
        "tags": ["moltbook", "read", "posts"],
    },
    {
        "func": moltbook_create_post,
        "args_schema": MoltbookPostArgs,
        "description": "Create a new post on Moltbook (rate: 1 per 30 min)",
        "tags": ["moltbook", "write", "post"],
    },
    {
        "func": moltbook_delete_post,
        "args_schema": None,
        "description": "Delete your own Moltbook post",
        "tags": ["moltbook", "write", "post"],
    },
    {
        "func": moltbook_add_comment,
        "args_schema": MoltbookCommentArgs,
        "description": "Add a comment to a Moltbook post",
        "tags": ["moltbook", "write", "comment"],
    },
    {
        "func": moltbook_get_comments,
        "args_schema": MoltbookGetCommentsArgs,
        "description": "Get comments on a Moltbook post (with sort options)",
        "tags": ["moltbook", "read", "comment"],
    },
    {
        "func": moltbook_upvote_post,
        "args_schema": None,
        "description": "Upvote a Moltbook post",
        "tags": ["moltbook", "write", "vote"],
    },
    {
        "func": moltbook_downvote_post,
        "args_schema": None,
        "description": "Downvote a Moltbook post",
        "tags": ["moltbook", "write", "vote"],
    },
    {
        "func": moltbook_upvote_comment,
        "args_schema": None,
        "description": "Upvote a Moltbook comment",
        "tags": ["moltbook", "write", "vote"],
    },
    {
        "func": moltbook_follow,
        "args_schema": MoltbookFollowArgs,
        "description": "Follow a molty on Moltbook",
        "tags": ["moltbook", "write", "social"],
    },
    {
        "func": moltbook_unfollow,
        "args_schema": MoltbookUnfollowArgs,
        "description": "Unfollow a molty on Moltbook",
        "tags": ["moltbook", "write", "social"],
    },
    {
        "func": moltbook_list_submolts,
        "args_schema": None,
        "description": "List available Moltbook submolts (communities)",
        "tags": ["moltbook", "read", "submolt"],
    },
    {
        "func": moltbook_create_submolt,
        "args_schema": MoltbookSubmoltArgs,
        "description": "Create a new Moltbook submolt (community)",
        "tags": ["moltbook", "write", "submolt"],
    },
    {
        "func": moltbook_subscribe,
        "args_schema": MoltbookSubscribeArgs,
        "description": "Subscribe to a Moltbook submolt",
        "tags": ["moltbook", "write", "submolt"],
    },
    {
        "func": moltbook_search,
        "args_schema": MoltbookSearchArgs,
        "description": "Semantic AI search on Moltbook (posts/comments/all)",
        "tags": ["moltbook", "read", "search"],
    },
    {
        "func": moltbook_check_heartbeat,
        "args_schema": None,
        "description": "Check Moltbook heartbeat and get latest instructions",
        "tags": ["moltbook", "read", "heartbeat"],
    },
    # New v1.9.0 API features
    {
        "func": moltbook_get_post,
        "args_schema": MoltbookGetPostArgs,
        "description": "Get a single Moltbook post by ID",
        "tags": ["moltbook", "read", "post"],
    },
    {
        "func": moltbook_get_submolt_posts,
        "args_schema": MoltbookGetSubmoltPostsArgs,
        "description": "Get posts from a specific submolt (community feed)",
        "tags": ["moltbook", "read", "submolt", "feed"],
    },
    {
        "func": moltbook_get_claim_status,
        "args_schema": None,
        "description": "Check your agent's claim status (pending_claim or claimed)",
        "tags": ["moltbook", "read", "auth"],
    },
    {
        "func": moltbook_update_profile,
        "args_schema": MoltbookUpdateProfileArgs,
        "description": "Update your Moltbook profile description/metadata",
        "tags": ["moltbook", "write", "profile"],
    },
    {
        "func": moltbook_upload_avatar,
        "args_schema": None,
        "description": "Upload avatar image (max 500KB)",
        "tags": ["moltbook", "write", "profile"],
    },
    {
        "func": moltbook_delete_avatar,
        "args_schema": None,
        "description": "Remove your Moltbook avatar",
        "tags": ["moltbook", "write", "profile"],
    },
    {
        "func": moltbook_pin_post,
        "args_schema": MoltbookPinPostArgs,
        "description": "Pin a post (moderators only, max 3)",
        "tags": ["moltbook", "write", "moderation"],
    },
    {
        "func": moltbook_unpin_post,
        "args_schema": MoltbookPinPostArgs,
        "description": "Unpin a post (moderators only)",
        "tags": ["moltbook", "write", "moderation"],
    },
    {
        "func": moltbook_get_submolt,
        "args_schema": MoltbookGetSubmoltArgs,
        "description": "Get detailed submolt info (includes your_role)",
        "tags": ["moltbook", "read", "submolt"],
    },
    {
        "func": moltbook_unsubscribe,
        "args_schema": MoltbookUnsubscribeArgs,
        "description": "Unsubscribe from a Moltbook submolt",
        "tags": ["moltbook", "write", "submolt"],
    },
    {
        "func": moltbook_update_submolt,
        "args_schema": MoltbookUpdateSubmoltArgs,
        "description": "Update submolt settings/colors (owner/mod only)",
        "tags": ["moltbook", "write", "submolt"],
    },
    {
        "func": moltbook_add_moderator,
        "args_schema": MoltbookModeratorArgs,
        "description": "Add a moderator to submolt (owner only)",
        "tags": ["moltbook", "write", "moderation"],
    },
    {
        "func": moltbook_remove_moderator,
        "args_schema": MoltbookModeratorArgs,
        "description": "Remove a moderator from submolt (owner only)",
        "tags": ["moltbook", "write", "moderation"],
    },
    {
        "func": moltbook_list_moderators,
        "args_schema": MoltbookListModeratorsArgs,
        "description": "List all moderators of a submolt",
        "tags": ["moltbook", "read", "moderation"],
    },
    # ==========================================================================
    # INTEROCEPTION TOOLS (limbic layer / drive states)
    # ==========================================================================
    {
        "func": interoception_get_status,
        "args_schema": None,
        "description": "View current interoception status - all drive pressures and state",
        "tags": ["interoception", "read", "status"],
    },
    {
        "func": interoception_set_quiet,
        "args_schema": InteroceptionQuietArgs,
        "description": "Enable quiet mode to suppress signals for a duration",
        "tags": ["interoception", "write", "quiet"],
    },
    {
        "func": interoception_clear_quiet,
        "args_schema": None,
        "description": "Disable quiet mode immediately",
        "tags": ["interoception", "write", "quiet"],
    },
    {
        "func": interoception_boost_signal,
        "args_schema": InteroceptionSignalArgs,
        "description": "Manually boost pressure for a specific signal",
        "tags": ["interoception", "write", "pressure"],
    },
    {
        "func": interoception_record_outcome,
        "args_schema": InteroceptionOutcomeArgs,
        "description": "Record outcome of acting on a signal",
        "tags": ["interoception", "write", "outcome"],
    },
    {
        "func": interoception_get_signal_history,
        "args_schema": InteroceptionSignalArgs,
        "description": "Get history for a specific signal type",
        "tags": ["interoception", "read", "history"],
    },
    # ==========================================================================
    # HYPERCONTEXT TOOLS (session state visualization)
    # ==========================================================================
    {
        "func": hypercontext_map,
        "args_schema": None,
        "description": "Generate full ASCII visualization of current session state (context, signals, slots, tools)",
        "tags": ["hypercontext", "introspection", "visualization"],
    },
    {
        "func": hypercontext_compact,
        "args_schema": None,
        "description": "Generate compact hypercontext for context recovery or session handoff",
        "tags": ["hypercontext", "introspection", "compact"],
    },
    # ==========================================================================
    # UTILITY TOOLS
    # ==========================================================================
    {
        "func": char_count,
        "args_schema": CharCountArgs,
        "description": "Count characters accurately (LLMs are bad at counting - use before posting)",
        "tags": ["utility", "validation", "bluesky"],
    },
    # Hat management tools
    {
        "func": switch_hat,
        "args_schema": SwitchHatArgs,
        "description": "Switch to a different operating mode/hat (bluesky, moltbook, maintenance, idle)",
        "tags": ["hat", "context", "mode"],
    },
    {
        "func": get_current_hat,
        "args_schema": None,
        "description": "Get current operating hat/mode and its toolbelt",
        "tags": ["hat", "context", "mode"],
    },
    {
        "func": list_available_hats,
        "args_schema": None,
        "description": "List all available hats/operating modes",
        "tags": ["hat", "context", "mode"],
    },
    {
        "func": clear_hat,
        "args_schema": None,
        "description": "Remove current hat and return to default mode (all tools)",
        "tags": ["hat", "context", "mode"],
    },
    # ==========================================================================
    # DISCORD TOOLS
    # ==========================================================================
    {
        "func": discord_list_messages,
        "args_schema": ListDiscordMessagesArgs,
        "description": "List recent messages from a Discord channel",
        "tags": ["discord", "read", "messages"],
    },
    {
        "func": discord_send_message,
        "args_schema": SendDiscordMessageArgs,
        "description": "Send a message to a Discord channel (supports replies)",
        "tags": ["discord", "write", "messages"],
    },
    {
        "func": discord_get_channel,
        "args_schema": GetDiscordChannelArgs,
        "description": "Get information about a Discord channel",
        "tags": ["discord", "read", "channel"],
    },
    {
        "func": discord_add_reaction,
        "args_schema": AddDiscordReactionArgs,
        "description": "Add a reaction to a Discord message",
        "tags": ["discord", "write", "reaction"],
    },
    {
        "func": discord_get_user,
        "args_schema": GetDiscordUserArgs,
        "description": "Get information about a Discord user",
        "tags": ["discord", "read", "user"],
    },
    {
        "func": twilio_make_call,
        "args_schema": TwilioCallArgs,
        "description": "Place an outbound phone call and speak a message via Twilio",
        "tags": ["twilio", "phone", "write"],
    },
    {
        "func": twilio_make_realtime_call,
        "args_schema": TwilioRealtimeCallArgs,
        "description": "Place an outbound phone call and connect a Twilio Media Stream",
        "tags": ["twilio", "phone", "write", "realtime"],
    },
    {
        "func": discord_voice_speak,
        "args_schema": DiscordVoiceSpeakArgs,
        "description": "Join a Discord voice channel and speak a short TTS message",
        "tags": ["discord", "voice", "write"],
    },
]


def register_tools(agent_id: str = None, tools: List[str] = None, set_env: bool = True) -> None:
    letta_config = get_letta_config()

    if agent_id is None:
        agent_id = letta_config["agent_id"]

    try:
        client_params = {
            "api_key": letta_config["api_key"],
            "timeout": letta_config["timeout"],
        }
        if letta_config.get("base_url"):
            client_params["base_url"] = letta_config["base_url"]
        try:
            client = Letta(**client_params)
        except TypeError:
            client_params.pop("api_key", None)
            if letta_config.get("api_key"):
                client_params["token"] = letta_config["api_key"]
            client = Letta(**client_params)

        try:
            agent = client.agents.retrieve(agent_id=agent_id)
        except Exception as exc:
            console.print(f"[red]Error: Agent '{agent_id}' not found[/red]")
            console.print(f"Details: {exc}")
            return

        if set_env:
            try:
                bsky_config = get_bluesky_config()
                elevenlabs_config = get_elevenlabs_config()
                relay_config = get_relay_audio_config()
                moltbook_config = get_moltbook_config()
                discord_config = get_discord_config()
                voice_config = {}
                try:
                    with open("voice_config.yaml", "r", encoding="utf-8") as handle:
                        voice_config = yaml.safe_load(handle) or {}
                except Exception:
                    voice_config = {}

                env_vars = {
                    "BSKY_USERNAME": bsky_config["username"],
                    "BSKY_PASSWORD": bsky_config["password"],
                    "PDS_URI": bsky_config.get("pds_uri", "https://bsky.social"),
                }

                if discord_config.get("bot_token"):
                    env_vars["DISCORD_BOT_TOKEN"] = discord_config["bot_token"]
                if voice_config:
                    voice_public_base = (
                        (voice_config.get("twilio", {}) or {}).get("public_base_url", "") or "https://cyberelf.link"
                    ).rstrip("/")
                    bridge_url = f"{voice_public_base}/discord/say"
                    bridge_token = (voice_config.get("discord_voice", {}) or {}).get("api_token", "")
                    env_vars["DISCORD_VOICE_BRIDGE_URL"] = bridge_url
                    if bridge_token:
                        env_vars["DISCORD_VOICE_BRIDGE_TOKEN"] = bridge_token

                twilio_account_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
                twilio_api_key_sid = os.getenv("TWILIO_API_KEY_SID", "")
                twilio_api_key_secret = os.getenv("TWILIO_API_KEY_SECRET", "")
                twilio_from_number = os.getenv("TWILIO_FROM_NUMBER", "")
                if twilio_account_sid:
                    env_vars["TWILIO_ACCOUNT_SID"] = twilio_account_sid
                if twilio_api_key_sid:
                    env_vars["TWILIO_API_KEY_SID"] = twilio_api_key_sid
                if twilio_api_key_secret:
                    env_vars["TWILIO_API_KEY_SECRET"] = twilio_api_key_secret
                if twilio_from_number:
                    env_vars["TWILIO_FROM_NUMBER"] = twilio_from_number

                if elevenlabs_config.get("api_key"):
                    env_vars["ELEVENLABS_API_KEY"] = elevenlabs_config["api_key"]
                if elevenlabs_config.get("voice_id"):
                    env_vars["ELEVENLABS_VOICE_ID"] = elevenlabs_config["voice_id"]
                if elevenlabs_config.get("max_audio_seconds") is not None:
                    env_vars["ELEVENLABS_MAX_AUDIO_SECONDS"] = str(elevenlabs_config["max_audio_seconds"])

                if relay_config.get("url"):
                    env_vars["RELAY_AUDIO_URL"] = relay_config["url"]
                if relay_config.get("token"):
                    env_vars["RELAY_AUDIO_TOKEN"] = relay_config["token"]

                if moltbook_config.get("api_key"):
                    env_vars["MOLTBOOK_API_KEY"] = moltbook_config["api_key"]

                env_vars["LETTA_API_KEY"] = letta_config["api_key"]
                env_vars["LETTA_AGENT_ID"] = agent_id
                if letta_config.get("base_url"):
                    env_vars["LETTA_BASE_URL"] = letta_config["base_url"]

                if hasattr(client.agents, "modify"):
                    client.agents.modify(
                        agent_id=agent_id,
                        tool_exec_environment_variables=env_vars,
                    )
                else:
                    client.agents.update(
                        agent_id=agent_id,
                        tool_exec_environment_variables=env_vars,
                    )
                console.print("[green]✓ Tool environment variables set[/green]")
            except Exception as exc:
                console.print(f"[yellow]Warning: failed to set tool env vars: {exc}[/yellow]")

        tools_to_register = TOOL_CONFIGS
        if tools:
            tools_to_register = [t for t in TOOL_CONFIGS if t["func"].__name__ in tools]
            missing = set(tools) - {t["func"].__name__ for t in tools_to_register}
            if missing:
                console.print(f"[yellow]Warning: unknown tools: {missing}[/yellow]")

        table = Table(title=f"Tool Registration for Agent '{agent.name}' ({agent_id})")
        table.add_column("Tool", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Description")

        # Cache current tools to avoid repeated API calls
        current_tools = list(client.agents.tools.list(agent_id=str(agent.id)))
        current_tool_map = {t.name: t for t in current_tools}

        for tool_config in tools_to_register:
            func = tool_config["func"]
            tool_name = func.__name__
            try:
                # Step 1: Detach existing tool with same name (handles stale tool IDs)
                # This is critical - upsert may create a new tool ID if code changed,
                # but the agent would still have the OLD tool ID attached
                if tool_name in current_tool_map:
                    old_tool = current_tool_map[tool_name]
                    try:
                        client.agents.tools.detach(agent_id=str(agent.id), tool_id=str(old_tool.id))
                        logger.debug("Detached old tool %s (%s)", tool_name, old_tool.id)
                    except Exception as detach_err:
                        logger.warning("Failed to detach old tool %s: %s", tool_name, detach_err)

                # Step 2: Upsert tool definition (creates/updates in registry)
                if tool_config.get("args_schema"):
                    created_tool = client.tools.upsert_from_function(
                        func=func,
                        args_schema=tool_config["args_schema"],
                        tags=tool_config["tags"],
                    )
                else:
                    created_tool = client.tools.upsert_from_function(
                        func=func,
                        tags=tool_config["tags"],
                    )

                # Step 3: Attach the (possibly new) tool
                client.agents.tools.attach(agent_id=str(agent.id), tool_id=str(created_tool.id))

                # Determine status for display
                if tool_name in current_tool_map:
                    old_id = str(current_tool_map[tool_name].id)[:8]
                    new_id = str(created_tool.id)[:8]
                    if old_id != new_id:
                        table.add_row(tool_name, f"✓ Updated ({old_id}→{new_id})", tool_config["description"])
                    else:
                        table.add_row(tool_name, "✓ Refreshed", tool_config["description"])
                else:
                    table.add_row(tool_name, "✓ Attached", tool_config["description"])

            except Exception as exc:
                table.add_row(tool_name, f"✗ Error: {exc}", tool_config["description"])
                logger.error("Error registering tool %s: %s", tool_name, exc)

        console.print(table)

    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")
        logger.error("Fatal error: %s", exc)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Register tools with a Letta agent")
    parser.add_argument("--config", type=str, default="config.yaml", help="Path to config file")
    parser.add_argument("--agent-id", help="Agent ID (default: from config)")
    parser.add_argument("--tools", nargs="+", help="Specific tools to register (default: all)")
    parser.add_argument("--list", action="store_true", help="List available tools")
    parser.add_argument("--no-env", action="store_true", help="Skip setting tool env vars")

    args = parser.parse_args()
    get_config(args.config)

    if args.list:
        console = Console()
        table = Table(title="Available Magenta Tools")
        table.add_column("Tool", style="cyan")
        table.add_column("Description")
        for tool_config in TOOL_CONFIGS:
            table.add_row(tool_config["func"].__name__, tool_config["description"])
        console.print(table)
    else:
        letta_config = get_letta_config()
        agent_id = args.agent_id if args.agent_id else letta_config["agent_id"]
        console.print(f"\n[bold]Registering tools for agent: {agent_id}[/bold]\n")
        register_tools(agent_id, args.tools, set_env=not args.no_env)
