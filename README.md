<p align="center">
  <img src="src/static/glass-48.svg" width="96" alt="Glassroom">
</p>

<h1 align="center">Glassroom</h1>

<p align="center"><strong>See what's really happening in your kid's Google Classroom.</strong></p>

<p align="center">
  <a href="https://github.com/sageframe-no-kaji/glassroom/releases/tag/v1.0.0"><img src="https://img.shields.io/badge/version-v1.0.0-blue" alt="v1.0.0"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT"></a>
  <img src="https://img.shields.io/badge/docker-ghcr.io-blue" alt="GHCR">
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/sageframe-dharma/glassroom-web/main/images/hero.png" alt="Glassroom dashboard" width="800">
</p>

---

Google Classroom was designed for teachers, not parents. There's no cross-class view, no way to see what's due across all your kid's classes at once, and no way to tell whether an assignment came with actual instructions or just a title.

Glassroom fixes this. One dashboard. Every class. Every assignment.

## What it does

- **One dashboard** for every class — missing, assigned, graded, all in one view
- **Stat cards** per class with color-coded completion indicators
- **PDF downloader** — pulls all Google Docs, Slides, and Sheets attachments
- **CSV export** at any time — full data, filterable by class or status
- **Works without API access** — uses browser automation the same way you would
- **Idempotent** — scrape as often as you want, only changes are recorded

## Who this is for

- **Parents tracking homework** across six classes with six different teachers
- **Parents of kids with IEPs** — verify whether accommodations involving materials and instructions are actually being honored
- **Parents of kids on medical leave** — confirm teachers are posting materials remotely
- **Special education advocates** — export structured, timestamped data for IEP meetings or BSEA hearings

---

## Install

### Requirements

[Docker Desktop](https://www.docker.com/get-started/) — Mac or Windows. That's it.

### Two commands

```bash
curl -O https://raw.githubusercontent.com/sageframe-no-kaji/glassroom/main/docker-compose.yml
docker compose up -d
```

Then open **http://localhost:3000**.

Glassroom pulls the pre-built image from GitHub Container Registry — no building, no Python, no source code needed.

### First-run setup (~2 minutes)

1. **Log in** — click "Open login browser." A tab opens showing a Chrome window inside the container. Sign in with your kid's school Google account. When Glassroom detects the Classroom homepage, the tab closes and setup continues.
2. **Select classes** — check which classes to track. Archived classes available too.
3. **Scrape** — Glassroom pulls all assignments in the background.
4. **Done** — you're on the dashboard.

After setup, scrapes run headlessly. Trigger a new one any time from the nav bar.

---

## Data & persistence

All data lives in a `data/` folder created next to your `docker-compose.yml`:

```
data/
├── classroom.db      — all assignments (SQLite)
├── config.json       — class selections and settings
└── downloads/        — PDFs organized by class
```

The Google session is stored in a Docker named volume (`glassroom-session`) — it persists across restarts and is never written to your filesystem.

```bash
docker compose down        # stop (data preserved)
docker compose up -d       # restart
docker compose down -v     # full reset — removes session
rm -rf data/               # remove database and downloads
```

---

## Updates

When a new version is released, pull and restart:

```bash
docker compose pull
docker compose up -d
```

---

## Running without Docker

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
PYTHONPATH=. python src/app.py
```

---

## What it reveals

Some teachers post 140 structured assignments with due dates, rubrics, and attachments. Others post 61 with nothing — same school, same kid. Glassroom makes the difference visible, class by class, assignment by assignment.

If your child has an IEP that requires home copies of classwork and slides, Glassroom shows you whether that's actually happening. Every empty description, every attachment-free assignment, every class with no due dates — all visible, all exportable.

---

## Built with the Ho System

Glassroom was designed and built using the [Ho System](https://atmarcus.net/work/ho-system) — a structured methodology for human-AI collaborative development. [View the Ho System on GitHub →](https://github.com/sageframe-no-kaji/ho-system)

---

## License

MIT — built by a parent who needed it, shared with every parent who needs it too.
