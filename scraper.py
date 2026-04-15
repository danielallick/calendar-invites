"""
Aixtron Financial Calendar Scraper → Google Calendar Bot
========================================================
Scrapes https://www.aixtron.com/en/press/events for upcoming financial dates,
uses Claude API to enrich descriptions, and creates Google Calendar events
via Gmail (sending .ics invites to yourself).

Designed to run daily via GitHub Actions.
"""

import os
import json
import re
import hashlib
import smtplib
import ssl
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ─── Configuration ───────────────────────────────────────────────────────────

EVENTS_URL = "https://www.aixtron.com/en/press/events"
SENT_EVENTS_FILE = "sent_events.json"  # tracks what we already sent
COMPANY = "AIXTRON SE"
TICKER = "AIXA.DE"

# Environment variables (set as GitHub Secrets)
CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "")
GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
CALENDAR_EMAIL = os.environ.get("CALENDAR_EMAIL", "")  # where to send invites


# ─── Scraping ────────────────────────────────────────────────────────────────

def scrape_aixtron_events() -> list[dict]:
    """Scrape the Aixtron events page and return structured event data."""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; CalendarBot/1.0)"
    }
    resp = requests.get(EVENTS_URL, headers=headers, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    events = []

    # Find all table rows in the events table
    for row in soup.select("table tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue

        # Extract event name from first cell
        event_name = cells[0].get_text(strip=True)
        if not event_name:
            continue

        # Extract date from second cell
        date_text = cells[1].get_text(strip=True)
        # Clean up the date text (remove "Date" prefix if present)
        date_text = re.sub(r"^Date\s*", "", date_text, flags=re.IGNORECASE).strip()

        # Parse the date
        event_date = parse_event_date(date_text)
        if not event_date:
            print(f"  ⚠ Could not parse date '{date_text}' for '{event_name}'")
            continue

        # Extract .ics link if available
        ics_link = None
        link_tag = row.find("a", href=re.compile(r"\.ics$", re.IGNORECASE))
        if link_tag:
            href = link_tag["href"]
            if href.startswith("/"):
                ics_link = f"https://www.aixtron.com{href}"
            else:
                ics_link = href

        # Create a stable ID from event name + date
        event_id = hashlib.sha256(
            f"{event_name}|{event_date.isoformat()}".encode()
        ).hexdigest()[:12]

        events.append({
            "id": event_id,
            "name": event_name,
            "date": event_date.isoformat(),
            "date_str": date_text,
            "ics_link": ics_link,
            "company": COMPANY,
            "ticker": TICKER,
        })

    print(f"✓ Scraped {len(events)} events from Aixtron website")
    return events


def parse_event_date(date_str: str) -> datetime | None:
    """Try multiple date formats to parse the event date."""
    formats = [
        "%B %d, %Y",      # "April 30, 2026"
        "%b %d, %Y",      # "Apr 30, 2026"
        "%d %B %Y",       # "30 April 2026"
        "%d.%m.%Y",       # "30.04.2026"
        "%Y-%m-%d",       # "2026-04-30"
        "%d/%m/%Y",       # "30/04/2026"
        "%m/%d/%Y",       # "04/30/2026"
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None


# ─── Claude Enrichment ───────────────────────────────────────────────────────

def enrich_with_claude(event: dict) -> str:
    """Use Claude API to generate a useful calendar invite description."""
    if not CLAUDE_API_KEY:
        print("  ⚠ No CLAUDE_API_KEY set, using basic description")
        return f"{event['company']} ({event['ticker']})\n{event['name']}\nDate: {event['date_str']}"

    prompt = f"""You are an investment analyst assistant. Generate a brief, useful
calendar invite description (3-5 sentences) for this financial event:

Company: {event['company']}
Ticker: {event['ticker']}
Event: {event['name']}
Date: {event['date_str']}

Include:
- What this event is and why it matters for investors
- What to watch for or prepare
- Any typical market impact of this type of event

Keep it concise and actionable. No markdown formatting, plain text only."""

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Content-Type": "application/json",
                "x-api-key": CLAUDE_API_KEY,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 300,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        description = data["content"][0]["text"]
        print(f"  ✓ Claude enriched: {event['name']}")
        return description
    except Exception as e:
        print(f"  ⚠ Claude API error: {e}")
        return f"{event['company']} ({event['ticker']})\n{event['name']}\nDate: {event['date_str']}"


# ─── Calendar Invite (.ics) Generation ───────────────────────────────────────

def generate_ics(event: dict, description: str) -> str:
    """Generate an .ics calendar file for the event."""
    dt = datetime.fromisoformat(event["date"])
    # All-day event (financial dates are typically full-day)
    dtstart = dt.strftime("%Y%m%d")
    dtend = (dt + timedelta(days=1)).strftime("%Y%m%d")
    now = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    uid = f"{event['id']}@aixtron-calendar-bot"

    # Escape special characters for iCalendar format
    summary = f"📊 {event['company']}: {event['name']}"
    desc_escaped = description.replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")
    summary_escaped = summary.replace(",", "\\,").replace(";", "\\;")

    ics = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//AixtronCalendarBot//EN
METHOD:REQUEST
BEGIN:VEVENT
UID:{uid}
DTSTART;VALUE=DATE:{dtstart}
DTEND;VALUE=DATE:{dtend}
DTSTAMP:{now}
SUMMARY:{summary_escaped}
DESCRIPTION:{desc_escaped}
LOCATION:https://www.aixtron.com/en/investors
STATUS:CONFIRMED
TRANSP:TRANSPARENT
BEGIN:VALARM
ACTION:DISPLAY
DESCRIPTION:Reminder
TRIGGER:-P1D
END:VALARM
BEGIN:VALARM
ACTION:DISPLAY
DESCRIPTION:Reminder
TRIGGER:-P7D
END:VALARM
END:VEVENT
END:VCALENDAR"""
    return ics


# ─── Email Sending ───────────────────────────────────────────────────────────

def send_calendar_invite(event: dict, ics_content: str, description: str):
    """Send the .ics file as an email calendar invite via Gmail SMTP."""
    if not all([GMAIL_ADDRESS, GMAIL_APP_PASSWORD, CALENDAR_EMAIL]):
        print("  ⚠ Email credentials not configured, skipping send")
        print(f"  Would send invite for: {event['name']} on {event['date_str']}")
        return False

    msg = MIMEMultipart("mixed")
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = CALENDAR_EMAIL
    msg["Subject"] = f"📊 {COMPANY}: {event['name']} – {event['date_str']}"

    # HTML body
    html_body = f"""
    <html><body>
    <h3>{event['company']} ({event['ticker']})</h3>
    <h2>{event['name']}</h2>
    <p><strong>Date:</strong> {event['date_str']}</p>
    <hr>
    <p>{description.replace(chr(10), '<br>')}</p>
    <hr>
    <p><small>Auto-generated by Aixtron Calendar Bot</small></p>
    </body></html>
    """
    msg.attach(MIMEText(html_body, "html"))

    # Attach .ics file (this creates the calendar invite)
    ics_part = MIMEBase("text", "calendar", method="REQUEST")
    ics_part.set_payload(ics_content.encode("utf-8"))
    encoders.encode_base64(ics_part)
    ics_part.add_header("Content-Disposition", "attachment", filename="invite.ics")
    ics_part.add_header("Content-Type", "text/calendar; method=REQUEST")
    msg.attach(ics_part)

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.send_message(msg)
        print(f"  ✓ Sent invite: {event['name']} → {CALENDAR_EMAIL}")
        return True
    except Exception as e:
        print(f"  ✗ Email send failed: {e}")
        return False


# ─── State Management ────────────────────────────────────────────────────────

def load_sent_events() -> set:
    """Load the set of event IDs we've already sent."""
    path = Path(SENT_EVENTS_FILE)
    if path.exists():
        data = json.loads(path.read_text())
        return set(data.get("sent_ids", []))
    return set()


def save_sent_events(sent_ids: set):
    """Persist the set of sent event IDs."""
    Path(SENT_EVENTS_FILE).write_text(
        json.dumps({"sent_ids": sorted(sent_ids), "updated": datetime.utcnow().isoformat()},
                    indent=2)
    )


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*60}")
    print(f"  Aixtron Calendar Bot – {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}\n")

    # 1. Scrape events
    events = scrape_aixtron_events()
    if not events:
        print("No events found. Exiting.")
        return

    # 2. Filter to future events only
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    future_events = [
        e for e in events
        if datetime.fromisoformat(e["date"]) >= today
    ]
    print(f"✓ {len(future_events)} future events (of {len(events)} total)")

    # 3. Check which events we already sent
    sent_ids = load_sent_events()
    new_events = [e for e in future_events if e["id"] not in sent_ids]
    print(f"✓ {len(new_events)} new events to process\n")

    if not new_events:
        print("No new events. All up to date!")
        return

    # 4. Process each new event
    for event in new_events:
        print(f"─── {event['name']} ({event['date_str']}) ───")

        # Enrich with Claude
        description = enrich_with_claude(event)

        # Generate .ics
        ics_content = generate_ics(event, description)

        # Send invite
        success = send_calendar_invite(event, ics_content, description)

        if success:
            sent_ids.add(event["id"])

    # 5. Save state
    save_sent_events(sent_ids)
    print(f"\n{'='*60}")
    print(f"  Done! Processed {len(new_events)} events.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
