import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

CONFIG_PATH = Path(__file__).parent.parent / "config.json"


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return _default_config()
    with CONFIG_PATH.open() as f:
        return json.load(f)


def save_config(config: dict[str, Any]) -> None:
    with CONFIG_PATH.open("w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")


def _default_config() -> dict[str, Any]:
    return {
        "selected_classes": [],
    }


def get_env(key: str, required: bool = True) -> str:
    load_dotenv()
    value = os.getenv(key)
    if required and not value:
        raise ValueError(f"Missing required env var: {key}")
    return value or ""
