# USAJOBS Daily Fetcher

A small automation that emails me the **full** list of federal IT jobs matching my saved search every weekday morning.

USAJOBS saved-search emails show only the newest posting and hide the rest behind a link. This job calls the official [USAJOBS Search API](https://developer.usajobs.gov/), pulls every open match, flags new and closing-soon postings, and sends one complete list to a dedicated job-alerts inbox.

## How it works

```
GitHub Actions (cron, weekdays 10:15 UTC)
        │
        ▼
usajobs_fetch.py ──► USAJOBS Search API (data.usajobs.gov, API key auth)
        │
        ▼
Gmail SMTP (app password) ──► job-alerts inbox
```

- **Filters** (in `SEARCH` at the top of the script): series 2210 (IT Management), open to the public and recent graduates, GS-5 to GS-9, full-time, permanent or term, nationwide.
- **Output:** postings sorted with NEW (last 2 days) first, then by closing date, with CLOSING SOON flagged when 5 days or less remain. Plain-text and HTML versions in one email.
- **No dependencies:** Python standard library only.

## Security choices

- API key and Gmail app password live in **GitHub Actions secrets**, never in code.
- The app password belongs to a **separate inbox used only for job alerts** (least privilege).
- The workflow token is limited to `contents: read`.
- The only third-party action used is GitHub's own `actions/checkout`.
- Failures exit non-zero, so GitHub emails a failure notice instead of failing silently.

## Setup

1. Request a free API key at https://developer.usajobs.gov/apirequest/.
2. In the alerts Gmail account, create an app password (Google Account → Security → 2-Step Verification → App passwords).
3. In this repo, go to **Settings → Secrets and variables → Actions** and add:
   - `USAJOBS_API_KEY`: the API key
   - `USAJOBS_EMAIL`: the email the key was registered with
   - `GMAIL_ADDRESS`: the alerts Gmail address
   - `GMAIL_APP_PASSWORD`: the 16-character app password (no spaces)
4. Go to **Actions → USAJOBS daily fetch → Run workflow** to test it.

## Run locally

```bash
python3 usajobs_fetch.py --sample tests/sample_response.json --dry-run   # no API key needed
python3 usajobs_fetch.py --dry-run                                       # real API, prints instead of emailing
```

## Notes

- GitHub can start scheduled runs a few minutes late.
- In public repos, GitHub pauses scheduled workflows after 60 days with no repository activity; any commit restarts them.
