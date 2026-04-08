# classroom-scraper

Google Classroom → Baserow scraper. Python + Playwright.

## Rules
- Full spec: see prompts/prompt.md
- Lint with ruff before completing any Ho
- Never touch fields prefixed ai_ or manual fields (notes, class_priority)
- All Baserow requests need header: Host: mandala.sageframe.net
- Secrets in .env only, never config.json

## Playwright
- Never use `wait_until="networkidle"` or `wait_for_load_state("networkidle")` — Google Classroom is a SPA with constant background polling and never reaches that state. It will always timeout.
- Use `wait_until="domcontentloaded"` for page.goto() calls, then wait for a specific element if you need content to be present.
