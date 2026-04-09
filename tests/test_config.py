"""Tests for src/config.py."""

import json

import pytest

from src.config import get_env, load_config, save_config


@pytest.fixture()
def tmp_config(tmp_path, monkeypatch):
    """Point CONFIG_PATH at a temp file for each test."""
    import src.config as config_module

    config_file = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "CONFIG_PATH", config_file)
    return config_file


class TestLoadConfig:
    def test_returns_defaults_when_file_missing(self, tmp_config):
        assert not tmp_config.exists()
        config = load_config()
        assert config == {"selected_classes": []}

    def test_reads_existing_file(self, tmp_config):
        data = {"selected_classes": [{"name": "Math", "course_url": "https://example.com"}]}
        tmp_config.write_text(json.dumps(data))
        config = load_config()
        assert config["selected_classes"][0]["name"] == "Math"

    def test_preserves_extra_keys(self, tmp_config):
        """config.json may have legacy Baserow keys — load_config must not strip them."""
        data = {
            "selected_classes": [],
            "baserow_table_id": 123,
            "baserow_field_ids": {"assignment_url": 456},
        }
        tmp_config.write_text(json.dumps(data))
        config = load_config()
        assert config["baserow_table_id"] == 123
        assert config["baserow_field_ids"]["assignment_url"] == 456


class TestSaveConfig:
    def test_writes_valid_json(self, tmp_config):
        data = {"selected_classes": [{"name": "Science", "course_url": "https://x.com"}]}
        save_config(data)
        assert tmp_config.exists()
        loaded = json.loads(tmp_config.read_text())
        assert loaded == data

    def test_round_trip(self, tmp_config):
        original = {"selected_classes": [], "custom_key": "value"}
        save_config(original)
        reloaded = load_config()
        assert reloaded == original


class TestGetEnv:
    def test_returns_value_when_set(self, monkeypatch):
        monkeypatch.setenv("TEST_GLASSROOM_KEY", "hello")
        # Avoid dotenv file interfering — point at non-existent .env
        import src.config as config_module
        monkeypatch.setattr(config_module, "load_dotenv", lambda: None)
        result = get_env("TEST_GLASSROOM_KEY", required=False)
        assert result == "hello"

    def test_raises_when_required_and_missing(self, monkeypatch):
        # Ensure the key is absent
        monkeypatch.delenv("DEFINITELY_NOT_A_REAL_ENV_VAR", raising=False)
        import src.config as config_module
        monkeypatch.setattr(config_module, "load_dotenv", lambda: None)
        with pytest.raises(ValueError, match="DEFINITELY_NOT_A_REAL_ENV_VAR"):
            get_env("DEFINITELY_NOT_A_REAL_ENV_VAR", required=True)

    def test_returns_empty_string_when_not_required_and_missing(self, monkeypatch):
        monkeypatch.delenv("ANOTHER_MISSING_VAR", raising=False)
        import src.config as config_module
        monkeypatch.setattr(config_module, "load_dotenv", lambda: None)
        result = get_env("ANOTHER_MISSING_VAR", required=False)
        assert result == ""
