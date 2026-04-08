# classroom-scraper

Scrapes a student's Google Classroom assignments and pushes them to a Baserow table. Uses Playwright browser automation with a saved login session (the Google Classroom API is blocked by the school district's Google Workspace admin). The scraper is idempotent — assignment URL is the unique key, rows are inserted or updated, never duplicated.

## Requirements

- Python 3.11+
- `pip install -r requirements.txt`
- Playwright browsers: `playwright install chromium`
- Self-hosted [Baserow](https://baserow.io) instance

## Setup

### 1. Configure .env

Copy `.env.example` to `.env` and fill in your Baserow credentials:

```
BASEROW_EMAIL=your@email.com
BASEROW_PASSWORD=yourpassword
BASEROW_TOKEN=          # leave blank — populated automatically on first run
```

The token is cached after the first successful auth and refreshed automatically when it expires. The password is never stored after the token is obtained.

### 2. Initialize Baserow

Creates the "CPSD Classroom" database, "Assignments" table, all fields, and the three dashboard views. Safe to re-run — skips anything that already exists.

```
python -m src.cli setup-baserow
```

### 3. Log in to Google Classroom

Opens a browser window. Complete the Google login manually. The session is saved to `~/.classroom-session/` and reused on future runs.

```
python -m src.cli login
```

### 4. Select classes to scrape

Presents a checkbox picker of your enrolled classes in the terminal. Selections are saved to `config.json`.

```
python -m src.cli select-classes
```

### 5. Scrape

```
python -m src.cli scrape
```

Scrapes all selected classes and pushes results to Baserow. Prints a summary on completion:

```
Baserow: 201 inserted, 0 updated, 0 unchanged
```

A full JSON log is written to `logs/scrape-{timestamp}.json` on every run.

Use `--dry-run` to run the full scrape and print JSON to stdout without writing to Baserow.

## Baserow views

Three views are created automatically by `setup-baserow`:

- **Do Now** — filter: status not in (Turned in, Graded, Done) and turn_in_required = true; sorted by due date ascending; grouped by class
- **All by Class** — no filter; grouped by class; sorted by due date descending
- **Needs AI Review** — filter: ai_work_type is empty; sorted by class then due date

## Notes

- Status and grades reflect the last scrape, not real-time data. Run `scrape` again to refresh.
- The `notes` and `class_priority` fields are never touched by the scraper — safe to edit manually in Baserow.
- The `ai_*` fields are reserved for a future AI analysis phase and are never written by the scraper.
- If the session expires, run `login` again to restore it.
