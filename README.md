# Glassroom

**See what's really happening in your kid's Google Classroom.**

Google Classroom is the most widely used learning platform in American K-12 education. Over 150 million students and teachers use it. But it was designed for teachers, not parents — and it shows. There's no cross-class view. No way to see what's due across all your kid's classes at once. No way to tell whether an assignment was actually given instructions, or if the teacher just posted a title and walked away. If your kid is absent, on medical leave, or struggling, Google Classroom tells you nothing useful.

Glassroom fixes this. It pulls every assignment from every class into one dashboard. It shows what's done, what's missing, and what was never properly assigned in the first place. It downloads all attached documents. And it gives you a clear, sortable, exportable record of what your kid's teachers are actually providing.

## Who this is for

- **Parents trying to keep track of homework.** Six classes, six different teachers, six different ways of using Classroom. Glassroom puts it all in one place.
- **Parents of kids with IEPs.** If your child's IEP says "provide home copies of classwork and slides" — Glassroom lets you verify whether that's actually happening. Every empty description field, every assignment with no attachments, every class with no due dates is visible.
- **Parents of kids on medical leave.** Your kid can't go to school. Their teachers are supposed to provide materials remotely. Are they? Glassroom shows you.
- **Special education advocates.** Preparing for a BSEA hearing or IEP meeting? Glassroom gives you timestamped, structured data showing exactly what was and wasn't provided to a student. Export to CSV, hand it to your attorney.

## What it does

- Logs into Google Classroom using your kid's school account (via browser automation — works even when the school blocks the Google Classroom API)
- Lets you select which classes to track
- Scrapes every assignment: title, description, due date, status, grade, points, attachments, teacher, week/topic grouping
- Shows everything in a single dashboard, sortable and filterable by class, status, and due date
- Downloads all Google Docs/Slides/Sheets attachments as PDFs, organized by class
- Exports to CSV at any time
- Idempotent — run it as often as you want, it only updates what's changed
- Logs every scrape with timestamps, building a record over time

## What it reveals

Google Classroom doesn't enforce any consistency across teachers. Some teachers post detailed weekly plans with clear due dates and attached rubrics. Others post a one-word title with no instructions, no attachments, no due date — and then grade students on work they were never given the tools to complete.

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
