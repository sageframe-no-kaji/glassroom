import json
import os
from pathlib import Path
from typing import Any, cast

from dotenv import load_dotenv

# Central data directory.  Override with GLASSROOM_DATA_DIR env var so Docker
# can bind-mount ./data:/app/data without touching source code.
DATA_DIR = Path(
    os.environ.get(
        "GLASSROOM_DATA_DIR",
        str(Path(__file__).parent.parent / "data"),
    )
)
DATA_DIR.mkdir(parents=True, exist_ok=True)

CONFIG_PATH = DATA_DIR / "config.json"
SETTINGS_PATH = DATA_DIR / "settings.json"


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return _default_config()
    with CONFIG_PATH.open() as f:
        return cast(dict[str, Any], json.load(f))


def save_config(config: dict[str, Any]) -> None:
    with CONFIG_PATH.open("w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")


def _default_config() -> dict[str, Any]:
    return {
        "selected_classes": [],
    }


def _default_settings() -> dict[str, Any]:
    return {
        "baserow_url": "",
        "baserow_token": "",
        "auto_export": False,
        "baserow_workspace_id": None,
        "baserow_database_id": None,
        "baserow_table_id": None,
        "baserow_field_ids": None,
    }


def load_settings() -> dict[str, Any]:
    if not SETTINGS_PATH.exists():
        return _default_settings()
    with SETTINGS_PATH.open() as f:
        return cast(dict[str, Any], json.load(f))


def save_settings(settings: dict[str, Any]) -> None:
    with SETTINGS_PATH.open("w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")


def get_env(key: str, required: bool = True) -> str:
    load_dotenv()
    value = os.getenv(key)
    if required and not value:
        raise ValueError(f"Missing required env var: {key}")
    return value or ""
