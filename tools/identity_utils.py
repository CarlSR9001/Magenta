"""Identity utilities for AT Protocol."""

import requests
from typing import Optional, Dict, Any

def resolve_handle(handle: str, pds_url: str = "https://bsky.social") -> Optional[str]:
    """Resolve a handle to a DID."""
    if handle.startswith("@"):
        handle = handle[1:]
    if handle.startswith("did:"):
        return handle
    
    url = f"{pds_url.rstrip('/')}/xrpc/com.atproto.identity.resolveHandle"
    try:
        resp = requests.get(url, params={"handle": handle}, timeout=10)
        if resp.status_code == 200:
            return resp.json().get("did")
    except Exception:
        pass
    return None

def get_did_document(did: str) -> Optional[Dict[str, Any]]:
    """Fetch the DID document for a given DID."""
    if did.startswith("did:plc:"):
        url = f"https://plc.directory/{did}"
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
    return None

def resolve_pds(did: str) -> Optional[str]:
    """Resolve the PDS endpoint for a DID."""
    doc = get_did_document(did)
    if not doc:
        return None
    
    services = doc.get("service", [])
    pds = next((s for s in services if s.get("id") == "#atproto_pds"), None)
    if pds:
        return pds.get("serviceEndpoint")
    return None

def get_profile(did: str, pds_url: str = "https://bsky.social", access_token: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Get profile info for a DID."""
    url = f"{pds_url.rstrip('/')}/xrpc/app.bsky.actor.getProfile"
    headers = {}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
        
    try:
        resp = requests.get(url, headers=headers, params={"actor": did}, timeout=10)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None
