from voice.voice_config import load_voice_config
import uvicorn


if __name__ == "__main__":
    cfg = load_voice_config()
    host = cfg.get("twilio", {}).get("listen_host", "0.0.0.0")
    port = int(cfg.get("twilio", {}).get("listen_port", 8790))
    log_level = cfg.get("local", {}).get("log_level", "info")
    uvicorn.run("voice.twilio_realtime_server:app", host=host, port=port, log_level=log_level)
