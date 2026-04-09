"""Tests for src/cli.py — argument parsing and command wiring.

Playwright-dependent commands (login, select-classes, scrape, dump-dom,
download-attachments) are tested at the argument-parsing level only.
The actual command functions are tested via mocks to verify they wire
to the correct underlying modules without running live browser automation.
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import src.cli as cli_module
from src.cli import main


def _run(args: list[str]) -> None:
    """Run the CLI main() with the given argument list."""
    import sys
    old = sys.argv
    sys.argv = ["src.cli"] + args
    try:
        main()
    finally:
        sys.argv = old


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


class TestArgParsing:
    def test_no_subcommand_exits(self):
        with pytest.raises(SystemExit):
            _run([])

    def test_unknown_subcommand_exits(self):
        with pytest.raises(SystemExit):
            _run(["not-a-command"])

    def test_scrape_default_flags(self):
        """scrape should default to dry_run=False, export_baserow=False."""
        captured = {}

        def fake_cmd(args):
            captured["dry_run"] = args.dry_run
            captured["export_baserow"] = args.export_baserow

        with patch.object(cli_module, "cmd_scrape", fake_cmd):
            _run(["scrape"])

        assert captured["dry_run"] is False
        assert captured["export_baserow"] is False

    def test_scrape_dry_run_flag(self):
        captured = {}

        def fake_cmd(args):
            captured["dry_run"] = args.dry_run

        with patch.object(cli_module, "cmd_scrape", fake_cmd):
            _run(["scrape", "--dry-run"])

        assert captured["dry_run"] is True

    def test_scrape_export_baserow_flag(self):
        captured = {}

        def fake_cmd(args):
            captured["export_baserow"] = args.export_baserow

        with patch.object(cli_module, "cmd_scrape", fake_cmd):
            _run(["scrape", "--export-baserow"])

        assert captured["export_baserow"] is True

    def test_download_attachments_force_flag(self):
        captured = {}

        def fake_cmd(args):
            captured["force"] = args.force

        with patch.object(cli_module, "cmd_download_attachments", fake_cmd):
            _run(["download-attachments", "--force"])

        assert captured["force"] is True

    def test_download_attachments_default_no_force(self):
        captured = {}

        def fake_cmd(args):
            captured["force"] = args.force

        with patch.object(cli_module, "cmd_download_attachments", fake_cmd):
            _run(["download-attachments"])

        assert captured["force"] is False


# ---------------------------------------------------------------------------
# cmd_scrape — dry-run path (no SQLite write, no Playwright)
# ---------------------------------------------------------------------------


class TestCmdScrapeDryRun:
    def test_dry_run_prints_json_not_writes_db(self, tmp_path, monkeypatch, capsys):
        fake_assignments = [
            {
                "assignment_url": "https://example.com/a/1",
                "title": "Test",
                "class_name": "Math",
            }
        ]

        monkeypatch.setattr(cli_module, "LOGS_DIR", tmp_path / "logs")

        with (
            patch("src.cli.load_config", return_value={"selected_classes": []}),
            patch("src.classroom.do_scrape", return_value=fake_assignments),
            patch("src.cli.db") as mock_db,
        ):
            import argparse
            args = argparse.Namespace(dry_run=True, export_baserow=False)
            # Import do_scrape so it's patchable via classroom module
            with patch("src.cli.cmd_scrape.__wrapped__", None, create=True):
                pass  # just ensure import doesn't fail

            # Call directly with a namespace
            from src.cli import cmd_scrape
            with patch("src.classroom.do_scrape", return_value=fake_assignments):
                cmd_scrape(args)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data[0]["title"] == "Test"
        mock_db.init_db.assert_not_called()


# ---------------------------------------------------------------------------
# cmd_scrape — SQLite write path
# ---------------------------------------------------------------------------


class TestCmdScrapeWrite:
    def test_writes_to_sqlite_by_default(self, tmp_path, monkeypatch):
        fake_assignments = [
            {"assignment_url": "https://example.com/a/1", "title": "HW"}
        ]

        monkeypatch.setattr(cli_module, "LOGS_DIR", tmp_path / "logs")
        mock_engine = MagicMock()

        with (
            patch("src.cli.load_config", return_value={"selected_classes": []}),
            patch("src.classroom.do_scrape", return_value=fake_assignments),
            patch("src.cli.db") as mock_db,
        ):
            mock_db.init_db.return_value = None
            mock_db.get_engine.return_value = mock_engine
            mock_db.upsert.return_value = "inserted"

            import argparse
            args = argparse.Namespace(dry_run=False, export_baserow=False)
            from src.cli import cmd_scrape
            with patch("src.classroom.do_scrape", return_value=fake_assignments):
                cmd_scrape(args)

        mock_db.init_db.assert_called_once()
        mock_db.upsert.assert_called_once()

    def test_scrape_counts_outcomes(self, tmp_path, monkeypatch, capsys):
        """inserted/updated/skipped counts should be reflected in printed output."""
        fake_assignments = [
            {"assignment_url": "https://example.com/a/1", "title": "HW1"},
            {"assignment_url": "https://example.com/a/2", "title": "HW2"},
            {"assignment_url": "https://example.com/a/3", "title": "HW3"},
        ]
        monkeypatch.setattr(cli_module, "LOGS_DIR", tmp_path / "logs")
        mock_engine = MagicMock()

        with (
            patch("src.cli.load_config", return_value={"selected_classes": []}),
            patch("src.classroom.do_scrape", return_value=fake_assignments),
            patch("src.cli.db") as mock_db,
        ):
            mock_db.init_db.return_value = None
            mock_db.get_engine.return_value = mock_engine
            # Return different outcomes per call
            mock_db.upsert.side_effect = ["inserted", "updated", "skipped"]

            import argparse
            args = argparse.Namespace(dry_run=False, export_baserow=False)
            from src.cli import cmd_scrape
            with patch("src.classroom.do_scrape", return_value=fake_assignments):
                cmd_scrape(args)

        out = capsys.readouterr().out
        assert "1 inserted" in out
        assert "1 updated" in out
        assert "1 unchanged" in out


# ---------------------------------------------------------------------------
# cmd_scrape — --export-baserow path
# ---------------------------------------------------------------------------


class TestCmdScrapeExportBaserow:
    def _run_export(self, monkeypatch: Any, tmp_path: Any, upsert_outcomes: list[str], db_outcome: str = "inserted") -> MagicMock:
        """Helper — run cmd_scrape(export_baserow=True) with configurable mock outcomes."""
        fake_assignments = [
            {"assignment_url": f"https://example.com/a/{i}", "title": f"HW{i}"}
            for i in range(len(upsert_outcomes))
        ]
        monkeypatch.setattr(cli_module, "LOGS_DIR", tmp_path / "logs")
        mock_engine = MagicMock()
        mock_client = MagicMock()
        mock_client.upsert.side_effect = upsert_outcomes

        with (
            patch("src.cli.load_config", return_value={
                "selected_classes": [],
                "baserow_table_id": 99,
                "baserow_field_ids": {"assignment_url": 1},
            }),
            patch("src.classroom.do_scrape", return_value=fake_assignments),
            patch("src.cli.db") as mock_db,
            patch("src.baserow_client.BaserowClient", return_value=mock_client),
        ):
            mock_db.init_db.return_value = None
            mock_db.get_engine.return_value = mock_engine
            mock_db.upsert.return_value = db_outcome

            import argparse
            args = argparse.Namespace(dry_run=False, export_baserow=True)
            from src.cli import cmd_scrape
            cmd_scrape(args)

        return mock_client

    def test_export_baserow_calls_baserow_upsert(self, monkeypatch, tmp_path):
        mock_client = self._run_export(monkeypatch, tmp_path, ["inserted"])
        mock_client.upsert.assert_called_once()

    def test_export_baserow_updated_branch(self, monkeypatch, tmp_path):
        """The elif outcome=='updated' branch must be exercised."""
        mock_client = self._run_export(monkeypatch, tmp_path, ["updated"])
        mock_client.upsert.assert_called_once()

    def test_export_baserow_skipped_branch(self, monkeypatch, tmp_path):
        """The else (skipped) branch must be exercised."""
        mock_client = self._run_export(monkeypatch, tmp_path, ["skipped"])
        mock_client.upsert.assert_called_once()


# ---------------------------------------------------------------------------
# cmd_setup_baserow
# ---------------------------------------------------------------------------


class TestCmdSetupBaserow:
    def test_calls_client_setup_and_create_views(self, monkeypatch):
        mock_client = MagicMock()
        mock_client.setup.return_value = {"selected_classes": []}

        with (
            patch("src.cli.load_config", return_value={"selected_classes": []}),
            patch("src.baserow_client.BaserowClient", return_value=mock_client),
        ):
            import argparse
            args = argparse.Namespace()
            from src.cli import cmd_setup_baserow
            cmd_setup_baserow(args)

        mock_client.setup.assert_called_once()
        mock_client.create_views.assert_called_once()


# ---------------------------------------------------------------------------
# cmd_login / cmd_select_classes
# ---------------------------------------------------------------------------


class TestCmdLogin:
    def test_calls_do_login(self):
        with patch("src.classroom.do_login") as mock_login:
            import argparse
            args = argparse.Namespace()
            from src.cli import cmd_login
            cmd_login(args)
        mock_login.assert_called_once()


class TestCmdSelectClasses:
    def test_calls_do_select_classes_with_config(self):
        fake_config: dict[str, object] = {"selected_classes": []}
        with (
            patch("src.cli.load_config", return_value=fake_config),
            patch("src.classroom.do_select_classes") as mock_select,
        ):
            import argparse
            args = argparse.Namespace()
            from src.cli import cmd_select_classes
            cmd_select_classes(args)
        mock_select.assert_called_once_with(fake_config)


# ---------------------------------------------------------------------------
# cmd_download_attachments
# ---------------------------------------------------------------------------


class TestCmdDownloadAttachments:
    def test_calls_do_download_attachments(self):
        fake_config: dict[str, object] = {"selected_classes": []}
        with (
            patch("src.cli.load_config", return_value=fake_config),
            patch("src.downloader.do_download_attachments") as mock_dl,
        ):
            import argparse
            args = argparse.Namespace(force=False)
            from src.cli import cmd_download_attachments
            cmd_download_attachments(args)
        mock_dl.assert_called_once_with(fake_config, force=False)

    def test_force_flag_passed_through(self):
        fake_config: dict[str, object] = {"selected_classes": []}
        with (
            patch("src.cli.load_config", return_value=fake_config),
            patch("src.downloader.do_download_attachments") as mock_dl,
        ):
            import argparse
            args = argparse.Namespace(force=True)
            from src.cli import cmd_download_attachments
            cmd_download_attachments(args)
        mock_dl.assert_called_once_with(fake_config, force=True)


# ---------------------------------------------------------------------------
# main() — argument dispatch wiring
# ---------------------------------------------------------------------------


class TestMainDispatch:
    def test_scrape_dispatches_to_cmd_scrape(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cli_module, "LOGS_DIR", tmp_path / "logs")
        called = {}

        def fake_cmd_scrape(args):
            called["invoked"] = True
            called["dry_run"] = args.dry_run

        with patch.object(cli_module, "cmd_scrape", fake_cmd_scrape):
            _run(["scrape"])

        assert called.get("invoked") is True
        assert called.get("dry_run") is False

    def test_scrape_dry_run_flag_parsed(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cli_module, "LOGS_DIR", tmp_path / "logs")
        called = {}

        def fake_cmd_scrape(args):
            called["dry_run"] = args.dry_run

        with patch.object(cli_module, "cmd_scrape", fake_cmd_scrape):
            _run(["scrape", "--dry-run"])

        assert called.get("dry_run") is True

    def test_download_attachments_dispatches(self):
        called = {}

        def fake_cmd(args):
            called["invoked"] = True
            called["force"] = args.force

        with patch.object(cli_module, "cmd_download_attachments", fake_cmd):
            _run(["download-attachments"])

        assert called.get("invoked") is True
        assert called.get("force") is False

