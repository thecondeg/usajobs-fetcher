#!/usr/bin/env python3
"""USAJOBS daily fetcher.

Pulls every open job that matches a saved set of filters from the official
USAJOBS Search API and emails the full list (not just the newest posting) to
a job-alerts inbox. Standard library only, so it runs anywhere Python 3.9+ does.

Environment variables (set as GitHub Actions secrets):
  USAJOBS_API_KEY      API key from https://developer.usajobs.gov/apirequest/
  USAJOBS_EMAIL        The email address the API key was registered with
  GMAIL_ADDRESS        Job-alerts Gmail address (sender and recipient)
  GMAIL_APP_PASSWORD   16-character Gmail app password for that account

Usage:
  python3 usajobs_fetch.py              # fetch and email
  python3 usajobs_fetch.py --dry-run    # fetch and print, no email
  python3 usajobs_fetch.py --sample FILE --dry-run   # render a saved API response
"""
import argparse
import datetime as dt
import html
import json
import os
import smtplib
import sys
import urllib.parse
import urllib.request
from email.message import EmailMessage

API_URL = "https://data.usajobs.gov/api/search"

# Same filters as the saved search on USAJOBS. Multiple values use ";".
SEARCH = {
    "JobCategoryCode": "2210",               # IT Management series
    "HiringPath": "public;graduates",        # Open to the public + recent graduates
    "PayGradeLow": "05",
    "PayGradeHigh": "09",
    "PositionScheduleTypeCode": "1",         # Full-time
    "PositionOfferingTypeCode": "15317;15319",  # Permanent; Term
    "ResultsPerPage": "500",
    "Fields": "Full",
    "SortField": "opendate",
    "SortDirection": "desc",
}

NEW_DAYS = 2         # posted within this many days -> marked NEW
CLOSING_DAYS = 5     # closes within this many days -> marked CLOSING SOON
SUBJECT_TAG = "[USAJOBS fetcher]"


def fetch(api_key, email):
    """Return all matching jobs, following pagination."""
    jobs, page = [], 1
    while True:
        params = dict(SEARCH, Page=str(page))
        req = urllib.request.Request(
            API_URL + "?" + urllib.parse.urlencode(params, safe=";"),
            headers={"Host": "data.usajobs.gov", "User-Agent": email,
                     "Authorization-Key": api_key},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.load(resp)
        result = data.get("SearchResult", {})
        jobs.extend(result.get("SearchResultItems", []))
        pages = int(result.get("UserArea", {}).get("NumberOfPages", 1) or 1)
        if page >= pages:
            return jobs
        page += 1


def _date(value):
    try:
        return dt.date.fromisoformat((value or "")[:10])
    except ValueError:
        return None


def summarize(item, today):
    d = item.get("MatchedObjectDescriptor", {})
    details = d.get("UserArea", {}).get("Details", {})
    plan = ", ".join(g.get("Code", "") for g in d.get("JobGrade", []) if g.get("Code"))
    low, high = details.get("LowGrade", ""), details.get("HighGrade", "")
    grade = f"{plan}-{low}" + (f" to {high}" if high and high != low else "") if low else plan
    pay = ""
    for r in d.get("PositionRemuneration", [])[:1]:
        try:
            lo, hi = float(r.get("MinimumRange", 0)), float(r.get("MaximumRange", 0))
            unit = {"PA": "/yr", "PH": "/hr"}.get(r.get("RateIntervalCode", ""), "")
            pay = f"${lo:,.0f}–${hi:,.0f}{unit}"
        except (TypeError, ValueError):
            pass
    opened, closes = _date(d.get("PublicationStartDate")), _date(d.get("ApplicationCloseDate"))
    flags = []
    if opened and (today - opened).days <= NEW_DAYS:
        flags.append("NEW")
    if closes and 0 <= (closes - today).days <= CLOSING_DAYS:
        flags.append("CLOSING SOON")
    return {
        "id": d.get("PositionID", ""),
        "title": d.get("PositionTitle", "(no title)"),
        "url": d.get("PositionURI", ""),
        "agency": " · ".join(x for x in (d.get("OrganizationName"), d.get("DepartmentName")) if x),
        "location": d.get("PositionLocationDisplay", ""),
        "grade": grade,
        "pay": pay,
        "opened": opened.isoformat() if opened else "",
        "closes": closes.isoformat() if closes else "",
        "flags": flags,
    }


def order(rows):
    """NEW first, then closing soonest."""
    return sorted(rows, key=lambda r: ("NEW" not in r["flags"], r["closes"] or "9999"))


def render(rows, today):
    new = sum("NEW" in r["flags"] for r in rows)
    subject = f"{SUBJECT_TAG} {today.isoformat()} · {len(rows)} open jobs ({new} new)"
    lines = [f"USAJOBS full list for {today.isoformat()}: {len(rows)} open jobs, {new} new.",
             "Filters: series 2210, public + recent graduates, GS-5 to GS-9, full-time, "
             "permanent or term, nationwide.", ""]
    for r in rows:
        tag = f"[{' / '.join(r['flags'])}] " if r["flags"] else ""
        lines += [f"{tag}{r['title']}", f"  {r['agency']}", f"  {r['location']}",
                  f"  {r['grade']} · {r['pay']} · open {r['opened']} → closes {r['closes']}",
                  f"  {r['url']}", ""]
    text = "\n".join(lines)

    cells = []
    for r in rows:
        tag = "".join(f'<b style="color:#b00">{html.escape(f)}</b> ' for f in r["flags"])
        cells.append(
            "<tr>"
            f'<td>{tag}<a href="{html.escape(r["url"])}">{html.escape(r["title"])}</a><br>'
            f'<small>{html.escape(r["agency"])}</small></td>'
            f"<td>{html.escape(r['location'])}</td>"
            f"<td>{html.escape(r['grade'])}<br>{html.escape(r['pay'])}</td>"
            f"<td>{html.escape(r['closes'])}</td>"
            "</tr>")
    body = (f"<p>{len(rows)} open jobs, {new} new. Filters: series 2210, public + recent graduates, "
            "GS-5 to GS-9, full-time, permanent or term, nationwide.</p>"
            '<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;font:14px sans-serif">'
            "<tr><th>Job</th><th>Location</th><th>Grade / pay</th><th>Closes</th></tr>"
            + "".join(cells) + "</table>")
    return subject, text, body


def send(subject, text, body, address, app_password):
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, address, address
    msg.set_content(text)
    msg.add_alternative(body, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as smtp:
        smtp.login(address, app_password)
        smtp.send_message(msg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print instead of emailing")
    ap.add_argument("--sample", help="render a saved API response instead of calling the API")
    args = ap.parse_args()

    today = dt.date.today()
    if args.sample:
        with open(args.sample, encoding="utf-8") as f:
            items = json.load(f)["SearchResult"]["SearchResultItems"]
    else:
        items = fetch(os.environ["USAJOBS_API_KEY"], os.environ["USAJOBS_EMAIL"])

    rows = order([summarize(i, today) for i in items])
    subject, text, body = render(rows, today)
    if args.dry_run:
        print(subject + "\n\n" + text)
        return
    send(subject, text, body, os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"])
    print(f"Sent: {subject}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # fail loudly so GitHub emails a failure notice
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
