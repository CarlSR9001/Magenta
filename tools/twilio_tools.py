"""Twilio call tools for Magenta.

Provides outbound call capability using Twilio's REST API and inline TwiML.
"""

from pydantic import BaseModel, Field


class TwilioCallArgs(BaseModel):
    to_number: str = Field(..., description="E.164 number to call (e.g., +15551234567)")
    message: str = Field(..., description="Message to speak during the call")
    voice: str = Field(default="alice", description="Twilio voice name (e.g., alice)")
    language: str = Field(default="en-US", description="Language code for TTS")


def twilio_make_call(to_number: str, message: str, voice: str = "alice", language: str = "en-US") -> str:
    """Place an outbound phone call and speak a message using Twilio <Say>.

    Requires env:
    - TWILIO_ACCOUNT_SID
    - TWILIO_API_KEY_SID
    - TWILIO_API_KEY_SECRET
    - TWILIO_FROM_NUMBER
    """
    import os
    import json
    import requests

    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    api_key_sid = os.getenv("TWILIO_API_KEY_SID", "")
    api_key_secret = os.getenv("TWILIO_API_KEY_SECRET", "")
    from_number = os.getenv("TWILIO_FROM_NUMBER", "")

    if not (account_sid and api_key_sid and api_key_secret and from_number):
        return json.dumps({
            "error": "Missing Twilio configuration. Set TWILIO_ACCOUNT_SID, TWILIO_API_KEY_SID, TWILIO_API_KEY_SECRET, TWILIO_FROM_NUMBER",
        })

    if not message.strip():
        return json.dumps({"error": "Message must be non-empty"})

    twiml = f"<Response><Say voice=\"{voice}\" language=\"{language}\">{message}</Say></Response>"

    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Calls.json"
    try:
        resp = requests.post(
            url,
            data={
                "To": to_number,
                "From": from_number,
                "Twiml": twiml,
            },
            auth=(api_key_sid, api_key_secret),
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
        return json.dumps({
            "status": "queued",
            "sid": payload.get("sid"),
            "to": payload.get("to"),
            "from": payload.get("from"),
        })
    except requests.HTTPError:
        try:
            details = resp.json()
        except Exception:
            details = resp.text if "resp" in locals() else ""
        return json.dumps({"error": "Twilio API error", "details": details})
    except Exception as e:
        return json.dumps({"error": str(e)})


class TwilioRealtimeCallArgs(BaseModel):
    to_number: str = Field(..., description="E.164 number to call (e.g., +15551234567)")
    stream_url: str = Field(..., description="Public wss:// URL for Twilio Media Streams")


def twilio_make_realtime_call(to_number: str, stream_url: str) -> str:
    """Place an outbound phone call and connect Twilio Media Streams.

    Requires env:
    - TWILIO_ACCOUNT_SID
    - TWILIO_API_KEY_SID
    - TWILIO_API_KEY_SECRET
    - TWILIO_FROM_NUMBER
    """
    import os
    import json
    import requests

    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    api_key_sid = os.getenv("TWILIO_API_KEY_SID", "")
    api_key_secret = os.getenv("TWILIO_API_KEY_SECRET", "")
    from_number = os.getenv("TWILIO_FROM_NUMBER", "")

    if not (account_sid and api_key_sid and api_key_secret and from_number):
        return json.dumps({
            "error": "Missing Twilio configuration. Set TWILIO_ACCOUNT_SID, TWILIO_API_KEY_SID, TWILIO_API_KEY_SECRET, TWILIO_FROM_NUMBER",
        })

    if not stream_url.startswith("wss://"):
        return json.dumps({"error": "stream_url must be a public wss:// URL"})

    twiml = f"""<Response>
  <Connect>
    <Stream url="{stream_url}" />
  </Connect>
</Response>"""

    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Calls.json"
    try:
        resp = requests.post(
            url,
            data={
                "To": to_number,
                "From": from_number,
                "Twiml": twiml,
            },
            auth=(api_key_sid, api_key_secret),
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
        return json.dumps({
            "status": "queued",
            "sid": payload.get("sid"),
            "to": payload.get("to"),
            "from": payload.get("from"),
        })
    except requests.HTTPError:
        try:
            details = resp.json()
        except Exception:
            details = resp.text if "resp" in locals() else ""
        return json.dumps({"error": "Twilio API error", "details": details})
    except Exception as e:
        return json.dumps({"error": str(e)})
