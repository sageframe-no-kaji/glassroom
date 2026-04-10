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

1. **Log in** — click "Open browser & log in" in the setup flow. A Chrome window will appear inside the app — open **http://localhost:6080/vnc.html** in a new browser tab and you'll see it. Sign in to your kid's school Google account. The setup page will detect it automatically.
2. **Select classes** — pick which classes to track.
3. **Scrape** — Glassroom pulls all assignments in the background.
4. **Done** — you're taken to the dashboard.

After the first setup, everything runs headlessly. You can trigger a new scrape any time from the nav bar.

### Logging in (more detail)

Glassroom uses browser automation (Playwright) to log into Google Classroom on your behalf. It never stores your password — it saves the browser session the same way Chrome does. During the login step, it opens a real Chrome window inside the container. You interact with it via a browser-based VNC viewer:

1. Open **http://localhost:6080/vnc.html** in your browser
2. You'll see a Chrome window
3. Sign in to Google with your kid's school account
4. Glassroom detects the login and closes the browser

You only need to do this once. The session persists across restarts.

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

You can't see this pattern inside Google Classroom. You have to click into every assignment in every class to discover that one teacher has 140 well-organized items and another has 40 items with zero due dates and zero instructions.

Glassroom makes this visible in seconds.

## Quick start

### Requirements
- [Docker](https://www.docker.com/get-started)

### Install and run

```bash
git clone https://github.com/sageframe-no-kaji/glassroom.git
cd glassroom
docker compose up
```

Open [http://localhost:3000](http://localhost:3000)

### First run

1. Click "Log In" — a browser window opens. Log in with your kid's school Google account.
2. Select the classes you want to track.
3. Click "Scrape" — Glassroom pulls all assignments. This takes a few minutes on first run.
4. Click "Download Attachments" — saves all Google Docs/Slides/Sheets as PDFs.
5. Browse the dashboard. Click "Export CSV" anytime.

### Subsequent runs

Just click "Scrape" again. Glassroom updates only what's changed. Run it weekly, daily, whenever you want.

## Optional: Baserow integration

If you use [Baserow](https://baserow.io) and want a more powerful spreadsheet view, Glassroom can push data to a Baserow table. Go to Settings, enter your Baserow URL and API token, and click "Setup Baserow." All data syncs automatically.

## How it works

Google Classroom's API is blocked by most school districts. Glassroom uses [Playwright](https://playwright.dev/) to automate a real browser session, the same way you'd browse Classroom yourself. Your kid's login session is saved locally and never leaves your machine. No data is sent anywhere.

The scraper navigates to each class's Classwork tab, reads every assignment, clicks into each one for full details, then stores everything in a local SQLite database. Attached Google Docs are downloaded as PDFs using Google's export URL pattern, authenticated by the saved session cookie.

## Schema

Every assignment record includes:

| Field | Description |
|---|---|
| title | Assignment name |
| assignment_url | Direct link — click to open in Classroom |
| class_name | Which class |
| week_label | Week or topic grouping (e.g. "Week 25: 4/6-4/10") |
| description | Full instruction text (empty if teacher didn't write any) |
| teacher | Teacher name |
| posted_date | When posted |
| due_date | When due (empty if no due date set) |
| points_possible | Points value |
| status | Assigned, Turned in, Graded, Missing, Done |
| turn_in_required | Whether it needs submission |
| grade | Score if graded |
| attachment_links | URLs of all attached documents |
| attachment_titles | Names of attached documents |
| first_seen_at | When Glassroom first found this assignment (never changes) |
| last_modified_at | When any field last changed |

Additional fields for notes (parent-editable) and AI analysis (future feature) are included in the schema.

## The accountability case

If your kid has an IEP, you already know the challenge: the school writes accommodations into the plan, and then you have no way to verify they're being implemented.

Glassroom gives you the data. If the IEP says "provide home copies of classwork and slides via Google Classroom," Glassroom shows you exactly which teachers are doing that and which aren't. If the IEP says "develop an action plan for missed work," Glassroom shows you whether any action plan is reflected in the assignment structure.

The empty fields are the evidence. An assignment with no description, no attachments, and no due date is an assignment a remote student cannot complete. A class with 40 such assignments is a class that was never adapted for the student's needs.

You don't need to argue this. The data argues it for you.

## Privacy

- All data stays on your machine. Nothing is sent to any server.
- The Google login session is stored locally and never shared.
- Glassroom is open source. Read the code. There are no analytics, no tracking, no telemetry.

## Built by a parent who needed it

This tool was built out of necessity. My daughter has an IEP and was on medical leave from a public school. Her teachers were supposed to provide assignments and materials remotely. Some did. Some didn't. I had no way to see the full picture until I built one.

The first time I ran Glassroom across all her classes, the contrast was immediate: one teacher had 140 assignments with weekly structure, due dates, and attached documents. Another had 61 items — zero due dates, zero descriptions, and empty templates that assumed in-class participation. A third had 40 items with one attachment across all of them.

That data changed our IEP meetings. It can change yours too.

## License

MIT

## Contributing

Issues and PRs welcome. If you're a parent who's been through this and want to help, reach out.
