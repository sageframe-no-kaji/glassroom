"""Shared pytest fixtures and safety guards.

Autouse guard: redirect the downloader's ``DOWNLOADS_DIR`` to a per-test temp
directory so no test can read, write, or delete the real ``data/downloads/``
folder. This exists because the ``/api/reset`` route calls
``shutil.rmtree(DOWNLOADS_DIR)``, and several reset tests exercised that route
without isolating the path — a full test run wiped real downloaded PDFs. The
reset route imports ``DOWNLOADS_DIR`` from ``src.downloader`` at call time, so
patching the attribute there is sufficient to cover it.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_downloads_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import src.downloader as downloader

    # Distinct name so it never collides with tests that create their own
    # `tmp_path / "downloads"` (e.g. test_reset_removes_downloads_dir).
    safe = tmp_path / "_downloads_guard"
    safe.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(downloader, "DOWNLOADS_DIR", safe)
