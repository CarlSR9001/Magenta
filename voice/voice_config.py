import os
from typing import Any, Dict

import yaml


DEFAULT_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "voice_config.yaml")


def load_voice_config(path: str | None = None) -> Dict[str, Any]:
    cfg_path = path or os.getenv("MAGENTA_VOICE_CONFIG", DEFAULT_CONFIG_PATH)
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
