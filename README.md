# Glassroom

**See what's really happening in your kid's Google Classroom.**

Google Classroom is the most widely used learning platform in American K-12 education. Over 150 million students and teachers use it. But it was designed for teachers, not parents — and it shows. There's no cross-class view. No way to see what's due across all your kid's classes at once. No way to tell whether an assignment was actually given instructions, or if the teacher just posted a title and walked away.

Glassroom fixes this.

## What it does

- Pulls every assignment from every class into one dashboard
- Shows what's done, what's missing, and what needs attention
- Downloads all Google Docs, Slides, and Sheets attachments as PDFs
- Exports everything to CSV at any time
- Works even when the school blocks the Google Classroom API
- Idempotent — run it as often as you want, it only updates what changed

## Who this is for

- **Parents trying to keep track of homework.** Six classes, six teachers, six different ways of using Classroom. Glassroom puts it all in one place.
- **Parents of kids with IEPs.** If your child's IEP says "provide home copies of classwork and slides" — Glassroom lets you verify whether that's actually happening. Every empty description, every assignment with no attachments, every class with no due dates is visible.
- **Parents of kids on medical leave.** Your kid can't go to school. Their teachers are supposed to provide materials remotely. Glassroom shows you whether they are.
- **Special education advocates.** Preparing for a BSEA hearing or IEP meeting? Glassroom gives you timestamped, structured data showing exactly what was and wasn't provided. Export to CSV, hand it to your attorney.

---

## Quick Start

### Requirements

- [Docker Desktop](https://www.docker.com/get-started/) (Mac, Windows, or Linux)

### Install and run

```bash
# 1. Download the project
git clone https://github.com/sageframe-no-kaji/glassroom.git
cd glassroom

# 2. Start Glassroom
docker compose up --build

# 3. Open your browser
open http://localhost:3000
```

The first time you run it, Glassroom will walk you through a short setup:

1. **Log in** — click "Open login browser" in the setup flow. A new tab opens with a Chrome window — sign in to your kid's school Google account. When Glassroom detects the login, the tab closes and the setup page continues automatically.
2. **Select classes** — pick which classes to track.
3. **Scrape** — Glassroom pulls all assignments in the background.
4. **Done** — you're taken to the dashboard.

After the first setup, everything runs headlessly. You can trigger a new scrape any time from the nav bar.

### Logging in (more detail)

Glassroom uses browser automation (Playwright) to log into Google Classroom on your behalf. It never stores your password — it saves the browser session the same way Chrome does.

During setup, click **Open login browser**. A new tab opens showing a real Chrome window running inside the container. Sign in to Google with your kid's school account. When Glassroom detects that you've reached the Classroom homepage, the tab closes automatically and setup continues.

You only need to do this once. The session persists across container restarts.

### Data persistence

All data is stored in the `data/` folder and persists across container restarts:

```
data/
├── classroom.db      — all assignments (SQLite)
├── config.json       — your class selections and settings
└── downloads/        — downloaded PDFs, organized by class
```

The Google login session is stored separately in a Docker named volume (`glassroom-session`) and is never accessible from the host filesystem.

### Stopping and restarting

```bash
# Stop
docker compose down

# Restart (data is preserved)
docker compose up

# Full reset (removes all data and session)
docker compose down -v
rm -rf data/
```

---

## Running without Docker

If you're comfortable with Python:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
PYTHONPATH=. python src/app.py
```

Open http://localhost:3000.

---

## What it reveals

Google Classroom doesn't enforce any consistency across teachers. Some post detailed weekly plans with clear due dates and attached rubrics. Others post a one-word title with no instructions, no attachments, no due date — and then grade students on work they were never given the tools to complete.

If your kid has an IEP, Glassroom makes it easy to verify whether accommodations involving materials, instructions, or home copies are actually being honored — class by class, assignment by assignment.

---

## License

MIT
