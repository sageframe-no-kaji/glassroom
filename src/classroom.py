"""Google Classroom Playwright automation: login, class selection, scraping."""

import base64
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.sync_api import BrowserContext, Page, sync_playwright

SESSION_DIR = Path.home() / ".classroom-session"
CLASSROOM_HOME = "https://classroom.google.com"

# Google Classroom stream item types (data-stream-item-type attribute)
# Verified by DOM inspection: assignment=1, question=4, material=5
_ITEM_TYPE_ASSIGNMENT = "1"
_ITEM_TYPE_QUESTION = "4"
_ITEM_TYPE_MATERIAL = "5"


# ---------------------------------------------------------------------------
# Browser helpers
# ---------------------------------------------------------------------------


def _open_context(p: Any, headless: bool = False) -> BrowserContext:
    """Launch a persistent Chromium context backed by ~/.classroom-session."""
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    return p.chromium.launch_persistent_context(str(SESSION_DIR), headless=headless)


def _scroll_fully(page: Page) -> None:
    """Scroll to the bottom repeatedly until no new content loads.

    Also clicks any 'Load more' button found during scrolling.
    """
    prev_height = 0
    for _ in range(30):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(800)
        try:
            btn = page.get_by_text("Load more", exact=True).first
            if btn.is_visible():
                btn.click()
                page.wait_for_timeout(1200)
        except Exception:
            pass
        height = int(page.evaluate("document.body.scrollHeight"))
        if height == prev_height:
            break
        prev_height = height


def _expand_view_more(page: Page) -> None:
    """Click all 'View more' buttons within topic sections.

    Google Classroom truncates long topic sections with a 'View more' button.
    We must expand them before parsing the item list or we miss items.
    """
    for _ in range(20):  # loop in case clicking one reveals another
        clicked = False
        for btn in page.query_selector_all("span:text-is('View more'), div:text-is('View more')"):
            try:
                if btn.is_visible():
                    btn.click()
                    page.wait_for_timeout(800)
                    clicked = True
            except Exception:
                pass
        if not clicked:
            break


def _check_session(page: Page) -> None:
    """Exit with a clear message if the session has expired."""
    if "accounts.google.com" in page.url:
        print("Session expired, run login first")
        sys.exit(1)


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------


def do_login() -> None:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = _open_context(p, headless=False)
        page = ctx.new_page()
        page.goto(CLASSROOM_HOME)
        print("Complete Google login in the browser window.")
        print("Waiting for classroom homepage (up to 5 minutes)...")
        # Block until the URL is classroom.google.com (user completes login).
        # Lambda predicate is more reliable than re.compile() with Playwright's
        # wait_for_url. Networkidle is intentionally NOT used — Classroom is a
        # SPA with constant background polling and never reaches that state.
        page.wait_for_url(
            lambda url: "classroom.google.com" in url,
            timeout=300_000,
        )
        # Brief pause so the persistent context flushes session cookies to disk
        # before we close it.
        page.wait_for_timeout(2000)
        print("Login saved.")
        ctx.close()


# ---------------------------------------------------------------------------
# select-classes
# ---------------------------------------------------------------------------


def do_select_classes(config: dict[str, Any]) -> None:
    from src.config import save_config

    with sync_playwright() as p:
        ctx = _open_context(p, headless=False)
        page = ctx.new_page()
        page.goto(CLASSROOM_HOME)
        _check_session(page)

        # Wait for class cards — more reliable than networkidle on a SPA.
        page.wait_for_selector("a[href*='/c/']", timeout=20_000)

        classes: list[dict[str, str]] = []
        seen: set[str] = set()
        for link in page.query_selector_all("a[href*='/c/']"):
            href = link.get_attribute("href") or ""
            if not re.search(r"/c/[^/]+/?$", href):
                continue
            url = (
                f"https://classroom.google.com{href}"
                if href.startswith("/")
                else href
            )
            if url in seen:
                continue
            seen.add(url)
            # Google Classroom cards render a single-letter color icon first,
            # then the full class name on the next line. Skip the icon line.
            lines = [ln.strip() for ln in link.inner_text().split("\n") if ln.strip()]
            name = lines[1] if len(lines) >= 2 else (lines[0] if lines else "")
            if name:
                classes.append({"name": name, "course_url": url})

        ctx.close()

    if not classes:
        print("No classes found. Ensure you are logged in to Google Classroom.")
        sys.exit(1)

    from InquirerPy import inquirer

    selected = inquirer.checkbox(
        message="Select classes to scrape (space=toggle, enter=confirm):",
        choices=[{"name": c["name"], "value": c} for c in classes],
    ).execute()

    if not selected:
        print("No classes selected.")
        sys.exit(0)

    config["selected_classes"] = selected
    save_config(config)
    print(f"Saved {len(selected)} class(es) to config.json.")


# ---------------------------------------------------------------------------
# scrape
# ---------------------------------------------------------------------------


def do_scrape(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Scrape all selected classes. Returns list of assignment dicts."""
    selected = config.get("selected_classes") or []
    if not selected:
        print("No classes selected. Run select-classes first.")
        sys.exit(1)

    all_assignments: list[dict[str, Any]] = []

    with sync_playwright() as p:
        ctx = _open_context(p, headless=False)
        for cls in selected:
            course_id = cls["course_url"].rstrip("/").split("/")[-1]
            print(f"Scraping: {cls['name']}", file=sys.stderr)
            assignments = _scrape_course(ctx, course_id, cls["name"])
            all_assignments.extend(assignments)
            print(f"  {len(assignments)} assignments found", file=sys.stderr)
        ctx.close()

    return all_assignments


def _scrape_course(
    ctx: BrowserContext, course_id: str, course_name: str
) -> list[dict[str, Any]]:
    """Scrape all assignments for one course. Returns assignment dicts."""
    list_page = ctx.new_page()
    list_page.goto(
        f"https://classroom.google.com/w/{course_id}/t/all",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    _check_session(list_page)
    # Wait for the SPA to render the classwork list before scrolling
    list_page.wait_for_selector("li[data-stream-item-id]", timeout=20_000)
    _scroll_fully(list_page)
    _expand_view_more(list_page)

    stubs = _parse_classwork_list(list_page, course_id, course_name)
    list_page.close()

    detail_page = ctx.new_page()
    assignments: list[dict[str, Any]] = []
    for stub in stubs:
        detail = _scrape_detail(detail_page, stub)
        if detail:
            assignments.append(detail)
        time.sleep(2)
    detail_page.close()

    return assignments


def _item_url(course_id: str, item_id: str, item_type: str) -> str:
    """Construct a direct URL to a classwork item detail page.

    Google Classroom stream item IDs from the DOM (data-stream-item-id) are
    decimal integers. The actual detail-page URLs use the same ID encoded in
    Base64 (standard, no padding). Both the course_id and item_id in URLs are
    Base64 strings — the course_id is already in that form in config.json; we
    must encode the item_id ourselves.

    URL patterns (verified from DOM + link inspection):
      type 1 (Assignment) → /c/{course_id}/a/{item_id_b64}/details
      type 5 (Material)   → /c/{course_id}/mc/{item_id_b64}
      type 6 (Question)   → /c/{course_id}/qu/{item_id_b64}
    """
    item_id_b64 = base64.b64encode(item_id.encode()).decode()
    base_url = f"https://classroom.google.com/c/{course_id}"
    if item_type == _ITEM_TYPE_MATERIAL:
        return f"{base_url}/mc/{item_id_b64}"
    # Assignments (type 1), Questions (type 4), and any unknown types all use
    # the /a/{id}/details URL pattern on the student-facing view.
    return f"{base_url}/a/{item_id_b64}/details"


def _type_label(item_type: str) -> str:
    """Return the human-readable type for Baserow's assignment_type field."""
    return {
        _ITEM_TYPE_ASSIGNMENT: "Assignment",
        _ITEM_TYPE_MATERIAL: "Material",
        _ITEM_TYPE_QUESTION: "Question",
    }.get(item_type, "Unknown")


def _parse_classwork_list(
    page: Page, course_id: str, course_name: str
) -> list[dict[str, Any]]:
    """Extract all stream items from the classwork page DOM.

    Google Classroom renders classwork as `li[data-stream-item-id]` elements
    with a `data-stream-item-type` attribute — there are NO `<a href>` links
    to individual items. We collect each item's ID and type, construct the
    detail URL ourselves, and extract the visible title and topic from the
    item's inner text and ancestor DOM.
    """
    raw: list[dict[str, Any]] = page.evaluate(
        """
        () => {
            const results = [];
            const skipText = new Set(['more_vert', 'More options', 'View more',
                                      'Collapse topic', 'Collapse all', '']);

            for (const li of document.querySelectorAll('li[data-stream-item-id]')) {
                const id = li.getAttribute('data-stream-item-id');
                const type = li.getAttribute('data-stream-item-type');

                // Parse title from inner text.
                // Line 0 = type label ("Assignment", "Material", "Completed Assignment", …)
                // Line 1 = title
                // Line 2 = date ("No due date", "Posted Mar 5", "Due Apr 10", …)
                const lines = li.innerText.trim().split('\\n')
                    .map(s => s.trim())
                    .filter(s => !skipText.has(s));
                const title = lines[1] || lines[0] || '';
                const dateLabel = lines[2] || '';

                // Find topic by walking up to the section container.
                // Topic sections are wrapped in a div[jscontroller='DxR4kb'].
                // The first non-button text line in that element is the topic name.
                let topic = null;
                let el = li.parentElement;
                while (el) {
                    if (el.getAttribute && el.getAttribute('jscontroller') === 'DxR4kb') {
                        const topicLines = el.innerText.split('\\n')
                            .map(s => s.trim())
                            .filter(s => s && !skipText.has(s));
                        const candidate = topicLines[0] || null;
                        // "No topic" is Google Classroom's unnamed section — treat as null
                        topic = (candidate && candidate !== 'No topic') ? candidate : null;
                        break;
                    }
                    el = el.parentElement;
                }

                results.push({ id, type, title, dateLabel, topic });
            }
            return results;
        }
        """
    )

    stubs: list[dict[str, Any]] = []
    for item in raw:
        item_id = item.get("id", "")
        item_type = item.get("type", "")
        title = item.get("title", "")
        if not item_id or not title:
            continue
        stubs.append(
            {
                "course_name": course_name,
                "assignment_url": _item_url(course_id, item_id, item_type),
                "title": title,
                "week_label": item.get("topic"),
                "assignment_type": _type_label(item_type),
            }
        )
    return stubs


def _scrape_detail(page: Page, stub: dict[str, Any]) -> dict[str, Any] | None:
    """Navigate to an assignment detail page and extract all fields.

    Returns None if the page fails to load.

    Selectors here are best-effort: Google Classroom uses auto-generated class
    names that can change. We try multiple selectors and fall back to regex
    over the visible page text for most fields.
    """
    url = stub["assignment_url"]
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        # Wait for the Angular SPA to render the detail content.
        # Timeline observed: domcontentloaded fires with ~90 char body (empty
        # shell), then main content renders at ~400ms (body ~930 chars), then
        # the "Your work" panel and attachments appear at ~600-1000ms.
        # Problem: on long-description pages the body exceeds 800 chars before
        # the panel loads, leaving the 500ms buffer too short to catch it.
        # Fix: after the body threshold, also wait for "Your work" to appear
        # (up to 3s), then add a buffer for attachments.
        try:
            page.wait_for_function(
                "() => document.body.innerText.length > 800",
                timeout=12_000,
            )
        except Exception:
            page.wait_for_timeout(4000)
        else:
            # Wait for "Your work" panel (assignments/questions). Materials
            # have no such panel — the 3s timeout lets them proceed naturally.
            try:
                page.wait_for_function(
                    '() => document.body.innerText.includes("Your work")',
                    timeout=3_000,
                )
            except Exception:
                pass  # Material or very delayed panel — proceed
            # Give attachment links time to finish rendering
            page.wait_for_timeout(500)
    except Exception as exc:
        print(f"  Warning: could not load {url}: {exc}", file=sys.stderr)
        return None

    visible = page.inner_text("body")

    # Google Classroom detail pages use auto-generated (obfuscated) CSS class
    # names that change without notice. All extraction below is regex-first on
    # the full body text, using patterns derived from observed page structure.
    #
    # Assignment header format in body text:
    #   {title}\nmore_vert\nMore options\n{teacher}\n•\n{date}\n{points?}
    # "Your work" panel format:
    #   Your work\n{status}\n...{grade?}...\n{Turn in|Mark as done?}

    # --- Teacher name and posted date (from header "•" separator pattern) ---
    teacher = ""
    posted_date = ""
    hdr = re.search(
        r"more_vert\s*\nMore options\s*\n(.+?)\n•\n(.+?)(?:\n|$)",
        visible,
    )
    if hdr:
        teacher = hdr.group(1).strip()
        posted_date = hdr.group(2).strip()

    # --- Due date: "Due …" anywhere ---
    due_date = ""
    due = re.search(r"[Dd]ue\s+(.+?)(?:\n|$)", visible)
    if due:
        due_date = due.group(1).strip()

    # --- Points: "100 points" anywhere ---
    points_possible: float | None = None
    pts = re.search(r"(\d+(?:\.\d+)?)\s*points?", visible, re.IGNORECASE)
    if pts:
        points_possible = float(pts.group(1))

    # --- Status + grade from "Your work" panel ---
    status = "Unknown"
    grade = ""
    yw = re.search(r"Your work\s*\n(.+?)(?:\nPrivate comments|\nClass comments|$)", visible, re.DOTALL)
    if yw:
        panel_text = yw.group(1)
        for s in ("Turned in", "Graded", "Missing", "Assigned", "Done"):
            if s in panel_text:
                status = s
                break
        gm = re.search(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", panel_text)
        if gm:
            grade = f"{gm.group(1)}/{gm.group(2)}"

    # --- Turn-in required: "Turn in" or "Mark as done" button text ---
    turn_in_required = bool(re.search(r"Turn in|Mark as done", visible))

    # --- Description: content between the header and attachments/comments ---
    # Try CSS selectors first (in case Google ever uses stable ones)
    description = ""
    for sel in [".nQgzcd", "[jsrenderer='jB2GAd']", "article"]:
        el = page.query_selector(sel)
        if el:
            description = el.inner_text().strip()
            break

    # --- Attachments: Google Drive / Docs / Forms / YouTube links ---
    attachment_links: list[str] = []
    attachment_titles: list[str] = []
    seen_hrefs: set[str] = set()

    for a in page.query_selector_all(
        "a[href*='docs.google.com'], "
        "a[href*='drive.google.com'], "
        "a[href*='forms.gle'], "
        "a[href*='youtube.com'], "
        ".iEGnAd a, .PoHNSb a, .RaRrU a"
    ):
        href = a.get_attribute("href") or ""
        if not href or href in seen_hrefs:
            continue
        raw_title = a.inner_text().strip()
        title = raw_title.split("\n")[0].strip() or a.get_attribute("aria-label") or href
        seen_hrefs.add(href)
        attachment_links.append(href)
        attachment_titles.append(title)

    return {
        "assignment_url": url,
        "class_name": stub["course_name"],
        "week_label": stub.get("week_label"),
        "title": stub.get("title", ""),
        "description": description,
        "teacher": teacher,
        "posted_date": posted_date,
        "due_date": due_date,
        "points_possible": points_possible,
        "category": stub.get("category"),
        "assignment_type": stub.get("assignment_type", "Unknown"),
        "status": status,
        "turn_in_required": turn_in_required,
        "grade": grade if grade else None,
        "attachment_links": "\n".join(attachment_links),
        "attachment_titles": "\n".join(attachment_titles),
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }
