"""Ho 4: Download Google Doc/Slides/Sheet attachments as PDFs via Playwright."""

import json
import re
import sys
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

from src.classroom import _open_context
from src.config import DATA_DIR

DOWNLOADS_DIR = DATA_DIR / "downloads"

_GDOC_RE = re.compile(r"docs\.google\.com/document/d/([^/?#]+)")
_GSLIDE_RE = re.compile(r"docs\.google\.com/presentation/d/([^/?#]+)")
_GSHEET_RE = re.compile(r"docs\.google\.com/spreadsheets/d/([^/?#]+)")
_GFORM_RE = re.compile(r"(forms\.gle/|docs\.google\.com/forms/)")
_GDRIVE_RE = re.compile(r"drive\.google\.com/file/d/([^/?#]+)")


def attachment_type(url: str) -> str:
    """Return a short human-readable type label for a given attachment URL."""
    if _GDOC_RE.search(url):
        return "Doc"
    if _GSLIDE_RE.search(url):
        return "Slides"
    if _GSHEET_RE.search(url):
        return "Sheet"
    if _GFORM_RE.search(url):
        return "Form"
    if _GDRIVE_RE.search(url):
        return "Drive"
    if "youtube.com" in url or "youtu.be" in url:
        return "Video"
    return "Link"


# ---------------------------------------------------------------------------
# Slug helpers
# ---------------------------------------------------------------------------


def _slugify(s: str) -> str:
    """Lowercase, spaces and special chars to hyphens, collapse duplicates."""
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s.strip("-")


def _class_folder_slug(class_name: str) -> str:
    """Derive a short, human-readable folder slug: {teacher_lastname}-{subject}.

    Handles the naming patterns seen in this project:
      "Science Heumann"                         → "heumann-science"
      "Mathematics: 002 - Boren, J"             → "boren-mathematics"
      "Social Studies/History: 004 - Lessage, P" → "lessage-social-studies"
      "Barker ELA -Ms. Joella"                  → "barker-ela"
    """
    name = class_name.strip()

    # Strategy 1: "… - Lastname, Initial" — last name follows " - "
    m = re.search(r"-\s*([A-Z][a-z]+),\s*[A-Z]", name)
    if m:
        teacher = m.group(1)
        subject_raw = name[: m.start()].strip()
        # Strip section numbers like ": 002" or ": 004" at the end
        subject_raw = re.sub(r":\s*\d+\s*$", "", subject_raw).strip()
        # Use only the primary subject before any "/" (e.g., "Social Studies")
        subject = subject_raw.split("/")[0].strip()
        return _slugify(f"{teacher}-{subject}")

    # Strategy 2: "-Ms./Mr./Mrs. Firstname" — teacher is the first token(s)
    m2 = re.search(r"-\s*(?:Ms|Mr|Mrs)\.\s*\w+", name, re.IGNORECASE)
    if m2:
        parts = name[: m2.start()].strip().split()
        if len(parts) >= 2:
            teacher, subject = parts[0], " ".join(parts[1:])
        else:
            teacher, subject = (parts[0] if parts else name), ""
        combined = f"{teacher}-{subject}" if subject else teacher
        return _slugify(combined)

    # Strategy 3: "Subject Lastname" — last word is the teacher's surname
    words = name.split()
    if len(words) >= 2:
        teacher = words[-1]
        subject = " ".join(words[:-1])
        return _slugify(f"{teacher}-{subject}")

    return _slugify(name)


def _title_slug(s: str, max_len: int = 60) -> str:
    """Slugify a title for use in a filename, truncated to max_len chars."""
    slug = _slugify(s)
    return slug[:max_len].rstrip("-")


def _make_pdf_filename(posted_date: str | None, title: str) -> str:
    date_part = posted_date if posted_date else "undated"
    return f"{date_part}_{_title_slug(title)}.pdf"


def _unique_filename(folder: Path, filename: str) -> str:
    """Append -2, -3, … to the stem if the filename already exists in folder."""
    if not (folder / filename).exists():
        return filename
    stem = filename[:-4]  # strip .pdf
    counter = 2
    candidate = f"{stem}-{counter}.pdf"
    while (folder / candidate).exists():
        counter += 1
        candidate = f"{stem}-{counter}.pdf"
    return candidate


# ---------------------------------------------------------------------------
# Export URL conversion
# ---------------------------------------------------------------------------


def _export_url(url: str) -> tuple[str, str] | None:
    """Return (export_url, doc_type) or None if not a downloadable Google doc."""
    m = _GDOC_RE.search(url)
    if m:
        return (
            f"https://docs.google.com/document/d/{m.group(1)}/export?format=pdf",
            "Google Doc",
        )
    m = _GSLIDE_RE.search(url)
    if m:
        return (
            f"https://docs.google.com/presentation/d/{m.group(1)}/export/pdf",
            "Google Slides",
        )
    m = _GSHEET_RE.search(url)
    if m:
        return (
            f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=pdf",
            "Google Sheets",
        )
    m = _GDRIVE_RE.search(url)
    if m:
        return (
            f"https://drive.google.com/uc?export=download&id={m.group(1)}",
            "Drive File",
        )
    return None


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------


def _load_manifest(downloads_dir: Path) -> dict[str, Any]:
    manifest_path = downloads_dir / "manifest.json"
    if manifest_path.exists():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _save_manifest(downloads_dir: Path, manifest: dict[str, Any]) -> None:
    downloads_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = downloads_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))


def _previously_downloaded(
    prev_manifest: dict[str, Any], class_slug: str, filename: str
) -> bool:
    """Return True if the file was successfully downloaded in a prior run."""
    cls_data = prev_manifest.get("classes", {}).get(class_slug, {})
    for f in cls_data.get("files", []):
        if f.get("filename") == filename and f.get("downloaded") is True:
            return True
    return False


# ---------------------------------------------------------------------------
# Main download command
# ---------------------------------------------------------------------------


def do_download_attachments(
    config: dict[str, Any],
    force: bool = False,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    from src.db import get_engine, get_session, init_db
    from src.models import Assignment

    init_db()
    engine = get_engine()

    print("Reading assignments from SQLite...", file=sys.stderr)
    with get_session(engine) as session:
        rows = session.query(Assignment).all()
        # Detach from session — we only need attribute values, not live ORM objects.
        # Pull out what we need while still in session scope.
        row_dicts = [
            {
                "id": r.id,
                "class_name": r.class_name or "",
                "title": r.title or "",
                "assignment_url": r.assignment_url or "",
                "posted_date": r.posted_date,
                "attachment_links": r.attachment_links or "",
                "attachment_titles": r.attachment_titles or "",
            }
            for r in rows
        ]
    print(f"  {len(row_dicts)} assignments loaded", file=sys.stderr)

    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    prev_manifest = _load_manifest(DOWNLOADS_DIR)

    # Build per-class work plan.
    # Structure: {class_slug: {class_name, assignments: [work_item, ...]}}
    # Each work_item: {row_id, assignment_title, assignment_url, posted_date,
    #                  source_url, attachment_title, export_url, doc_type}
    plan: dict[str, dict[str, Any]] = {}

    for row in row_dicts:
        links_raw = row.get("attachment_links") or ""
        titles_raw = row.get("attachment_titles") or ""

        if not links_raw.strip():
            continue

        class_name = str(row.get("class_name") or "")
        class_slug = _class_folder_slug(class_name) if class_name else "unknown"

        if class_slug not in plan:
            plan[class_slug] = {"class_name": class_name, "assignments": []}

        row_id = row.get("id")
        assignment_title = row.get("title") or ""
        assignment_url = row.get("assignment_url") or ""
        posted_date = row.get("posted_date") or None

        links = [ln.strip() for ln in links_raw.split("\n") if ln.strip()]
        titles = [t.strip() for t in titles_raw.split("\n") if t.strip()]
        # Pad titles list if shorter than links (shouldn't happen, but be safe)
        while len(titles) < len(links):
            titles.append("")

        for link, att_title in zip(links, titles):
            result = _export_url(link)
            plan[class_slug]["assignments"].append(
                {
                    "row_id": row_id,
                    "assignment_title": assignment_title,
                    "assignment_url": assignment_url,
                    "posted_date": posted_date,
                    "source_url": link,
                    "attachment_title": att_title,
                    "export_url": result[0] if result else None,
                    "doc_type": result[1] if result else None,
                }
            )

    # Count total work items for progress display
    total = sum(len(v["assignments"]) for v in plan.values())
    if total == 0:
        print("No attachments found. Nothing to download.")
        return {"downloaded": 0, "skipped": 0, "classes": 0}

    # Build the new manifest skeleton — stats are accumulated during download
    new_manifest: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "classes": {},
    }

    counter = 0

    with sync_playwright() as p:
        ctx = _open_context(p, headless=True)
        page = ctx.new_page()

        # Verify session is still valid before starting
        page.goto(
            "https://classroom.google.com",
            wait_until="domcontentloaded",
            timeout=20_000,
        )
        if "accounts.google.com" in page.url:
            print("Session expired, run login first")
            ctx.close()
            sys.exit(1)

        for class_slug, cls_data in plan.items():
            class_name = cls_data["class_name"]
            assignments = cls_data["assignments"]

            class_folder = DOWNLOADS_DIR / class_slug
            class_folder.mkdir(parents=True, exist_ok=True)

            cls_manifest: dict[str, Any] = {
                "class_name": class_name,
                "total_assignments": len(
                    {a["assignment_url"] for a in assignments}
                ),
                "total_attachments": len(assignments),
                "downloaded": 0,
                "skipped": 0,
                "files": [],
            }
            new_manifest["classes"][class_slug] = cls_manifest

            for item in assignments:
                counter += 1
                source_url = item["source_url"]
                exp_url = item["export_url"]
                att_title = item["attachment_title"]
                ass_title = item["assignment_title"]
                posted_date = item["posted_date"]

                # Non-Google-Doc URLs: skip
                if exp_url is None:
                    cls_manifest["skipped"] += 1
                    cls_manifest["files"].append(
                        {
                            "filename": None,
                            "assignment_title": ass_title,
                            "assignment_url": item["assignment_url"],
                            "source_url": source_url,
                            "attachment_title": att_title,
                            "db_row_id": item["row_id"],
                            "downloaded": False,
                            "skip_reason": "Not a Google Doc/Slides/Sheet",
                        }
                    )
                    print(
                        f"[{counter}/{total}] {class_slug}: skip — {source_url[:60]}",
                        file=sys.stderr,
                    )
                    if on_progress:
                        on_progress(counter, total)
                    continue

                filename = _make_pdf_filename(posted_date, ass_title or att_title)
                filename = _unique_filename(class_folder, filename)
                dest_path = class_folder / filename

                # Idempotency check (unless --force)
                if not force and _previously_downloaded(prev_manifest, class_slug, filename) and dest_path.exists():
                    cls_manifest["downloaded"] += 1
                    size = dest_path.stat().st_size
                    cls_manifest["files"].append(
                        {
                            "filename": filename,
                            "assignment_title": ass_title,
                            "assignment_url": item["assignment_url"],
                            "source_url": source_url,
                            "attachment_title": att_title,
                            "db_row_id": item["row_id"],
                            "downloaded": True,
                            "file_size_bytes": size,
                        }
                    )
                    print(
                        f"[{counter}/{total}] {class_slug}: {filename} (already downloaded)",
                        file=sys.stderr,
                    )
                    if on_progress:
                        on_progress(counter, total)
                    continue

                # Attempt download
                try:
                    with page.expect_download(timeout=60_000) as dl_info:
                        try:
                            page.goto(
                                exp_url,
                                wait_until="commit",
                                timeout=30_000,
                            )
                        except Exception:
                            # goto may raise for download-only responses; that's OK
                            pass

                    download = dl_info.value
                    download.save_as(str(dest_path))
                    size = dest_path.stat().st_size

                    cls_manifest["downloaded"] += 1
                    cls_manifest["files"].append(
                        {
                            "filename": filename,
                            "assignment_title": ass_title,
                            "assignment_url": item["assignment_url"],
                            "source_url": source_url,
                            "attachment_title": att_title,
                            "db_row_id": item["row_id"],
                            "downloaded": True,
                            "file_size_bytes": size,
                        }
                    )
                    if on_progress:
                        on_progress(counter, total)
                    print(
                        f"[{counter}/{total}] {class_slug}: {filename} (OK)",
                        file=sys.stderr,
                    )

                except Exception as exc:
                    # Check if session expired mid-run
                    if "accounts.google.com" in page.url:
                        print("Session expired mid-run, run login first")
                        ctx.close()
                        _save_manifest(DOWNLOADS_DIR, new_manifest)
                        sys.exit(1)

                    err_str = str(exc)
                    # Classify common errors
                    if "403" in err_str or "Forbidden" in err_str:
                        reason = "Access denied"
                    elif "404" in err_str or "Not Found" in err_str:
                        reason = "Not found"
                    elif "Timeout" in err_str or "timeout" in err_str:
                        reason = "Download timed out"
                    else:
                        reason = f"Error: {err_str[:120]}"

                    cls_manifest["skipped"] += 1
                    cls_manifest["files"].append(
                        {
                            "filename": None,
                            "assignment_title": ass_title,
                            "assignment_url": item["assignment_url"],
                            "source_url": source_url,
                            "attachment_title": att_title,
                            "db_row_id": item["row_id"],
                            "downloaded": False,
                            "skip_reason": reason,
                        }
                    )
                    if on_progress:
                        on_progress(counter, total)
                    print(
                        f"[{counter}/{total}] {class_slug}: {filename} FAILED — {reason}",
                        file=sys.stderr,
                    )

                time.sleep(1)

        ctx.close()

    _save_manifest(DOWNLOADS_DIR, new_manifest)
    print("Manifest saved to downloads/manifest.json")

    # Print summary
    total_dl = sum(c["downloaded"] for c in new_manifest["classes"].values())
    total_sk = sum(c["skipped"] for c in new_manifest["classes"].values())
    print(f"Done: {total_dl} downloaded, {total_sk} skipped")
    return {
        "downloaded": total_dl,
        "skipped": total_sk,
        "classes": len(new_manifest["classes"]),
    }
