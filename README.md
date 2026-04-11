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

Glassroom fixes this. One dashboard. Every Glassroom fi assignGlassroom fixes this. One dashboard. Every Glassroom fi assignG mGlaingGlassroom fixes this. One dashboiewGlassroom fixes this. One dashboard. Every Glassroom fi assignGlassroom fixes this. One dashpulls alGlassroom fcs, SlidGlassroom fixes this. One dashboard. Every Glassroom fi assignGlassroom fixes this. One dashboard. Every Glassroom fi assignG mGlaingGlassroom fixes this. tiGlassroom fixes this. One dashboard. Every Glassroom fi assignGlassroom fixes this. nges are Glassroom fixes this. One dashboard. Every Glassroom fi assignGlassrooix classesGlassroom fixes tnt teachers
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
2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.sroom pulls all assign2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2un2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2 in a `data/` folder created next to your `2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.2.QLit2.2.2.2.2─ config.json       — class selections and settings
└── downloads/        — PDFs organized by class
```

The Google sessThn iThe Google sessThn iThe Google ses(`glThe Google sessThn iThe Google sessThn iThe Google ses(`glThe Google sessThn iThe Google sessThn iThe Google ses(` downThe Google sessThn iThe Googld)
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

## License

MIT — built by a parent who needed it, shared with every parent who needs it too.
