import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import src.db as db
from src.config import load_config

LOGS_DIR = Path(__file__).parent.parent / "logs"


def cmd_setup_baserow(args: argparse.Namespace) -> None:
    from src.baserow_client import BaserowClient

    config = load_config()
    client = BaserowClient()
    config = client.setup(config)
    print("Creating views...")
    client.create_views(config)


def cmd_login(args: argparse.Namespace) -> None:
    from src.classroom import do_login

    do_login()


def cmd_select_classes(args: argparse.Namespace) -> None:
    from src.classroom import do_select_classes

    do_select_classes(load_config())


def cmd_dump_dom(args: argparse.Namespace) -> None:
    """Dump all hrefs and visible text from the classwork page of the first selected class."""
    from playwright.sync_api import sync_playwright

    from src.classroom import _open_context, _scroll_fully

    config = load_config()
    selected = config.get("selected_classes") or []
    if not selected:
        print("No classes selected. Run select-classes first.")
        sys.exit(1)

    cls = selected[0]
    course_id = cls["course_url"].rstrip("/").split("/")[-1]
    url = f"https://classroom.google.com/w/{course_id}/t/all"
    print(f"Dumping DOM for: {cls['name']}", file=sys.stderr)
    print(f"URL: {url}", file=sys.stderr)

    with sync_playwright() as p:
        ctx = _open_context(p, headless=False)
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        # Wait for Angular to render classwork content — 8s gives the SPA time to boot
        page.wait_for_timeout(8000)
        _scroll_fully(page)

        # Dump the outerHTML of the first few assignment-looking elements so we
        # can identify the correct tag/attributes for clicking.
        # Collect all stream item stubs before clicking anything
        stubs = page.evaluate("""
            () => [...document.querySelectorAll('li[data-stream-item-id]')].map(li => ({
                id: li.getAttribute('data-stream-item-id'),
                type: li.getAttribute('data-stream-item-type'),
                text: li.innerText.trim().split('\\n').filter(s => s.trim()).slice(0, 3),
            }))
        """)

        before_url = page.url

        # Try clicking the li directly
        first_li = page.query_selector("li[data-stream-item-id]")
        after_click_url = None
        page_title_after = None
        if first_li:
            first_li.click()
            page.wait_for_timeout(3000)
            after_click_url = page.url
            page_title_after = page.title()

        # Also try navigating directly to a constructed URL for the first assignment item
        # Pattern guesses based on data-stream-item-type:
        #   type 1 = Assignment  → /c/{cid}/a/{id}/details
        #   type 5 = Material    → /c/{cid}/mc/{id}
        #   type 6 = Question    → /c/{cid}/qu/{id}
        course_id_local = url.split("/w/")[1].split("/")[0]
        constructed_urls = []
        for stub in stubs[:3]:
            item_id = stub["id"]
            item_type = stub["type"]
            if item_type == "1":
                constructed_urls.append(f"/c/{course_id_local}/a/{item_id}/details")
            elif item_type == "5":
                constructed_urls.append(f"/c/{course_id_local}/mc/{item_id}")
            elif item_type == "6":
                constructed_urls.append(f"/c/{course_id_local}/qu/{item_id}")
            else:
                constructed_urls.append(f"type={item_type} id={item_id}")

        ctx.close()

    LOGS_DIR.mkdir(exist_ok=True)
    out = LOGS_DIR / "dump-stubs.json"
    out.write_text(json.dumps({
        "before_url": before_url,
        "after_click_url": after_click_url,
        "page_title_after_click": page_title_after,
        "url_changed": before_url != after_click_url,
        "constructed_url_guesses": constructed_urls,
        "stubs": stubs[:5],
    }, indent=2))
    print(f"Written to {out}")


def cmd_download_attachments(args: argparse.Namespace) -> None:
    from src.downloader import do_download_attachments

    do_download_attachments(load_config(), force=args.force)


def cmd_scrape(args: argparse.Namespace) -> None:
    from src.classroom import do_scrape

    config = load_config()
    assignments = do_scrape(config)

    LOGS_DIR.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = LOGS_DIR / f"scrape-{ts}.json"
    log_path.write_text(json.dumps(assignments, indent=2, ensure_ascii=False))
    print(f"Log: {log_path}", file=sys.stderr)
    print(f"Scraped: {len(assignments)} assignments", file=sys.stderr)

    if args.dry_run:
        print(json.dumps(assignments, indent=2, ensure_ascii=False))
        return

    # Write to SQLite (default)
    db.init_db()
    engine = db.get_engine()
    inserted = updated = skipped = 0
    for assignment in assignments:
        outcome = db.upsert(assignment, engine=engine)
        if outcome == "inserted":
            inserted += 1
        elif outcome == "updated":
            updated += 1
        else:
            skipped += 1

    print(f"SQLite: {inserted} inserted, {updated} updated, {skipped} unchanged")

    # Optionally also push to Baserow
    if args.export_baserow:
        from src.baserow_client import BaserowClient

        client = BaserowClient()
        table_id = config["baserow_table_id"]
        field_ids = config["baserow_field_ids"]

        br_inserted = br_updated = br_skipped = 0
        for assignment in assignments:
            outcome = client.upsert(assignment, table_id, field_ids)
            if outcome == "inserted":
                br_inserted += 1
            elif outcome == "updated":
                br_updated += 1
            else:
                br_skipped += 1

        print(
            f"Baserow: {br_inserted} inserted, {br_updated} updated, {br_skipped} unchanged"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="src.cli",
        description="Glassroom — Google Classroom scraper",
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.required = True

    sp = subparsers.add_parser("setup-baserow", help="Create Baserow database, table, and all fields")
    sp.set_defaults(func=cmd_setup_baserow)

    sp = subparsers.add_parser("login", help="Save Google Classroom browser session")
    sp.set_defaults(func=cmd_login)

    sp = subparsers.add_parser("select-classes", help="Choose which classes to scrape")
    sp.set_defaults(func=cmd_select_classes)

    sp = subparsers.add_parser("scrape", help="Scrape selected classes and write to SQLite")
    sp.add_argument(
        "--dry-run",
        action="store_true",
        help="Print scraped JSON without writing to any storage",
    )
    sp.add_argument(
        "--export-baserow",
        action="store_true",
        help="Also push scraped data to Baserow after writing to SQLite",
    )
    sp.set_defaults(func=cmd_scrape)

    sp = subparsers.add_parser("dump-dom", help="Dump classwork page links for debugging selectors")
    sp.set_defaults(func=cmd_dump_dom)

    sp = subparsers.add_parser(
        "download-attachments",
        help="Download Google Doc/Slides/Sheet attachments as PDFs",
    )
    sp.add_argument(
        "--force",
        action="store_true",
        help="Re-download all files, even if already present in manifest",
    )
    sp.set_defaults(func=cmd_download_attachments)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
