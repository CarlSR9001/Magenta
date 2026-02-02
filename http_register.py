#!/usr/bin/env python3
"""Direct HTTP tool registration with aggressive retry logic.

Bypasses potential SDK issues by using raw HTTP calls and verifying
each attachment individually with retries.
"""

import json
import logging
import time
import requests
from config_loader import get_letta_config, get_config
from register_tools import TOOL_CONFIGS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

get_config("config.yaml")
letta_config = get_letta_config()

API_KEY = letta_config["api_key"]
BASE_URL = letta_config.get("base_url", "https://api.letta.com")
AGENT_ID = letta_config["agent_id"]

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}


def api_get(endpoint, params=None):
    """Make GET request to Letta API."""
    url = f"{BASE_URL}/v1{endpoint}"
    resp = requests.get(url, headers=HEADERS, params=params, timeout=60)
    resp.raise_for_status()
    return resp.json()


def api_patch(endpoint):
    """Make PATCH request to Letta API."""
    url = f"{BASE_URL}/v1{endpoint}"
    resp = requests.patch(url, headers=HEADERS, timeout=60)
    resp.raise_for_status()
    return resp.json()


def api_put(endpoint, data):
    """Make PUT request to Letta API."""
    url = f"{BASE_URL}/v1{endpoint}"
    resp = requests.put(url, headers=HEADERS, json=data, timeout=60)
    resp.raise_for_status()
    return resp.json()


def get_all_attached_tools():
    """Get all tools attached to agent with full pagination."""
    tools = []
    after = None
    seen_ids = set()

    while True:
        params = {"after": after} if after else {}
        try:
            result = api_get(f"/agents/{AGENT_ID}/tools", params)
            items = result if isinstance(result, list) else result.get("items", [])

            if not items:
                break

            new_items = [t for t in items if t["id"] not in seen_ids]
            if not new_items:
                break

            for t in new_items:
                seen_ids.add(t["id"])
                tools.append(t)

            after = items[-1]["id"]
        except Exception as e:
            logger.warning(f"Pagination error: {e}")
            break

    return tools


def detach_all_tools():
    """Detach all tools from the agent."""
    tools = get_all_attached_tools()
    logger.info(f"Detaching {len(tools)} existing tools...")

    for tool in tools:
        try:
            api_patch(f"/agents/{AGENT_ID}/tools/detach/{tool['id']}")
            logger.info(f"  Detached: {tool['name']}")
        except Exception as e:
            logger.warning(f"  Failed to detach {tool['name']}: {e}")

    # Wait for consistency
    time.sleep(3)

    # Verify clean
    for _ in range(5):
        remaining = get_all_attached_tools()
        if not remaining:
            break
        logger.info(f"  Still {len(remaining)} tools, cleaning...")
        for tool in remaining:
            try:
                api_patch(f"/agents/{AGENT_ID}/tools/detach/{tool['id']}")
            except:
                pass
        time.sleep(2)

    logger.info("All tools detached")


def get_tool_by_name(name):
    """Find a tool ID by name from the organization's tools."""
    # Search in all tools (not just attached)
    try:
        result = api_get("/tools", params={"limit": 100})
        items = result if isinstance(result, list) else result.get("items", [])
        for t in items:
            if t.get("name") == name:
                return t
    except Exception as e:
        logger.warning(f"Error searching tools: {e}")
    return None


def verify_tool_attached(tool_name, max_retries=5, delay=2):
    """Verify a tool is attached with retries."""
    for i in range(max_retries):
        tools = get_all_attached_tools()
        if any(t["name"] == tool_name for t in tools):
            return True
        if i < max_retries - 1:
            time.sleep(delay)
    return False


def attach_tool_with_retry(tool_id, tool_name, max_retries=3):
    """Attach a tool with verification and retry."""
    for attempt in range(max_retries):
        try:
            api_patch(f"/agents/{AGENT_ID}/tools/attach/{tool_id}")
            time.sleep(1)  # Wait for consistency

            if verify_tool_attached(tool_name, max_retries=3, delay=1):
                return True

            logger.info(f"    Attachment not verified, retry {attempt + 1}")
        except Exception as e:
            logger.warning(f"    Attach error: {e}")

        time.sleep(2)

    return False


def register_single_tool(tool_config):
    """Register and attach a single tool using raw HTTP."""
    from inspect import signature, getsource
    import textwrap

    func = tool_config["func"]
    tool_name = func.__name__

    # Build the tool payload for upsert
    # Get function source code
    try:
        source = getsource(func)
        # Dedent the source
        source = textwrap.dedent(source)
    except Exception:
        source = ""

    # Get function signature for args schema
    sig = signature(func)

    # Build JSON schema from function signature or args_schema
    if tool_config.get("args_schema"):
        schema = tool_config["args_schema"].model_json_schema()
    else:
        # Build simple schema from signature
        properties = {}
        required = []
        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue
            prop = {"type": "string"}  # Default
            if param.annotation != param.empty:
                ann = param.annotation
                if ann == int:
                    prop = {"type": "integer"}
                elif ann == float:
                    prop = {"type": "number"}
                elif ann == bool:
                    prop = {"type": "boolean"}
                elif ann == str:
                    prop = {"type": "string"}
            properties[param_name] = prop
            if param.default == param.empty:
                required.append(param_name)

        schema = {
            "type": "object",
            "properties": properties,
        }
        if required:
            schema["required"] = required

    # Upsert the tool
    payload = {
        "name": tool_name,
        "source_code": source,
        "source_type": "python",
        "json_schema": schema,
        "tags": tool_config.get("tags", []),
    }

    try:
        result = api_put("/tools/", payload)
        tool_id = result.get("id")
        if not tool_id:
            return False, "No tool ID returned"

        # Attach to agent
        if attach_tool_with_retry(tool_id, tool_name):
            return True, None
        else:
            return False, "Failed to verify attachment"

    except requests.HTTPError as e:
        # If upsert fails, try to find existing tool
        existing = get_tool_by_name(tool_name)
        if existing:
            tool_id = existing["id"]
            if attach_tool_with_retry(tool_id, tool_name):
                return True, None
        return False, str(e)
    except Exception as e:
        return False, str(e)


def main():
    """Main registration flow."""
    print(f"\n=== HTTP DIRECT TOOL REGISTRATION ===")
    print(f"Agent: {AGENT_ID}")
    print(f"Base URL: {BASE_URL}\n")

    # Step 1: Clean slate
    print("Step 1: Detaching all existing tools...")
    detach_all_tools()
    print()

    # Step 2: Register tools one by one
    print(f"Step 2: Registering {len(TOOL_CONFIGS)} tools...")
    success = []
    failed = []

    for i, tool_config in enumerate(TOOL_CONFIGS, 1):
        tool_name = tool_config["func"].__name__
        ok, err = register_single_tool(tool_config)

        if ok:
            print(f"  [{i:2d}/{len(TOOL_CONFIGS)}] ✓ {tool_name}")
            success.append(tool_name)
        else:
            print(f"  [{i:2d}/{len(TOOL_CONFIGS)}] ✗ {tool_name}: {err}")
            failed.append(tool_name)

        # Small delay between tools
        time.sleep(0.5)

    print()

    # Step 3: Final verification
    print("Step 3: Final verification (waiting 5s for consistency)...")
    time.sleep(5)

    final_tools = get_all_attached_tools()
    final_names = sorted(set(t["name"] for t in final_tools))

    print(f"\n=== FINAL RESULT: {len(final_names)} unique tools attached ===")
    for name in final_names:
        print(f"  - {name}")

    print(f"\nSuccess: {len(success)}")
    if failed:
        print(f"Failed: {len(failed)} - {failed}")

    # Check for expected tools
    expected = {t["func"].__name__ for t in TOOL_CONFIGS}
    found = set(t["name"] for t in final_tools)
    missing = expected - found

    if missing:
        print(f"\n⚠️  MISSING: {missing}")

        # Try one more round of aggressive attachment for missing tools
        print("\nAttempting aggressive retry for missing tools...")
        for tool_config in TOOL_CONFIGS:
            tool_name = tool_config["func"].__name__
            if tool_name in missing:
                existing = get_tool_by_name(tool_name)
                if existing:
                    print(f"  Retrying {tool_name}...")
                    for _ in range(5):
                        try:
                            api_patch(f"/agents/{AGENT_ID}/tools/attach/{existing['id']}")
                            time.sleep(2)
                        except:
                            pass

        # Final check
        time.sleep(3)
        final_tools = get_all_attached_tools()
        final_names = set(t["name"] for t in final_tools)
        still_missing = expected - final_names

        if still_missing:
            print(f"\n⚠️  Still missing after retry: {still_missing}")
        else:
            print("\n✓ All tools now attached after retry!")
    else:
        print("\n✓ All expected tools are attached!")


if __name__ == "__main__":
    main()
