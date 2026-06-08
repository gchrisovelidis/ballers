"""
notify.py — Air Ballers Match Notification
Reads data.json, checks for a new upcoming match, and emails all recipients
with a styled HTML email + Google Calendar link + .ics attachment.
"""

import json
import os
import smtplib
import urllib.parse
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta

# ── Paths ────────────────────────────────────────────────────────────────────
DATA_FILE           = "data.json"
LAST_NOTIFIED_FILE  = "last_notified.json"
RECIPIENTS_FILE     = "recipients.txt"

# ── Config ───────────────────────────────────────────────────────────────────
TEAM_NAME           = "Air Ballers"
LEAGUE_NAME         = "Thessaloniki Amateur League"
MATCH_DURATION_HRS  = 2          # assumed game length for calendar end time
SITE_URL            = "https://gchrisovelidis.github.io/ballers_v2"

SENDER_EMAIL        = os.environ["GMAIL_ADDRESS"]
SENDER_PASSWORD     = os.environ["GMAIL_APP_PASSWORD"]

# ── Greek locale helpers ──────────────────────────────────────────────────────
DAYS_GR   = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]
MONTHS_GR = ["Ιανουαρίου", "Φεβρουαρίου", "Μαρτίου", "Απριλίου", "Μαΐου", "Ιουνίου",
             "Ιουλίου", "Αυγούστου", "Σεπτεμβρίου", "Οκτωβρίου", "Νοεμβρίου", "Δεκεμβρίου"]


# ── Helpers ──────────────────────────────────────────────────────────────────

def load_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def load_recipients() -> list[str]:
    try:
        with open(RECIPIENTS_FILE, "r", encoding="utf-8") as f:
            return [
                line.strip()
                for line in f
                if line.strip() and not line.startswith("#")
            ]
    except FileNotFoundError:
        return []


def parse_datetime(upcoming: dict) -> datetime | None:
    """Parse date + time from the upcoming match dict. Handles common formats."""
    date_str = upcoming.get("date", "")
    time_str = upcoming.get("time", "19:00")

    # Normalize time — strip seconds if present ("19:00:00" → "19:00")
    if time_str.count(":") == 2:
        time_str = time_str[:5]

    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            dt = datetime.strptime(f"{date_str} {time_str}", f"{fmt} %H:%M")
            return dt
        except ValueError:
            continue
    return None


def format_display_date(dt: datetime) -> str:
    return f"{DAYS_GR[dt.weekday()]}, {dt.day} {MONTHS_GR[dt.month - 1]} {dt.year}"


def match_id(upcoming: dict) -> str:
    """Unique string identifying a match — date + opponent."""
    return f"{upcoming.get('date', '')}_{upcoming.get('opponent', '')}".strip("_")


def is_new_match(upcoming: dict, last_notified: dict) -> bool:
    if not upcoming:
        return False
    return match_id(upcoming) != last_notified.get("match_id")


def save_last_notified(upcoming: dict) -> None:
    with open(LAST_NOTIFIED_FILE, "w", encoding="utf-8") as f:
        json.dump({"match_id": match_id(upcoming)}, f, indent=2, ensure_ascii=False)


# ── Calendar builders ────────────────────────────────────────────────────────

def build_gcal_url(upcoming: dict, dt: datetime) -> str | None:
    try:
        dt_end  = dt + timedelta(hours=MATCH_DURATION_HRS)
        fmt     = "%Y%m%dT%H%M%S"
        opponent = upcoming.get("opponent", "TBD")
        venue    = upcoming.get("venue", "")

        params = {
            "action":   "TEMPLATE",
            "text":     f"{TEAM_NAME} vs {opponent}",
            "dates":    f"{dt.strftime(fmt)}/{dt_end.strftime(fmt)}",
            "details":  f"{LEAGUE_NAME}\n{TEAM_NAME} vs {opponent}\n\n{SITE_URL}",
            "location": venue,
        }
        return "https://calendar.google.com/calendar/render?" + urllib.parse.urlencode(params)
    except Exception as e:
        print(f"⚠️  Could not build Google Calendar URL: {e}")
        return None


def build_ics(upcoming: dict, dt: datetime) -> str | None:
    try:
        dt_end   = dt + timedelta(hours=MATCH_DURATION_HRS)
        now_utc  = datetime.utcnow()
        fmt      = "%Y%m%dT%H%M%S"
        opponent = upcoming.get("opponent", "TBD")
        venue    = upcoming.get("venue", "")

        return (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//Air Ballers//Basketball//EN\r\n"
            "CALSCALE:GREGORIAN\r\n"
            "METHOD:PUBLISH\r\n"
            "BEGIN:VEVENT\r\n"
            f"DTSTART:{dt.strftime(fmt)}\r\n"
            f"DTEND:{dt_end.strftime(fmt)}\r\n"
            f"DTSTAMP:{now_utc.strftime(fmt)}Z\r\n"
            f"SUMMARY:{TEAM_NAME} vs {opponent}\r\n"
            f"LOCATION:{venue}\r\n"
            f"DESCRIPTION:{LEAGUE_NAME} — {TEAM_NAME} vs {opponent}\\n{SITE_URL}\r\n"
            "STATUS:CONFIRMED\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
    except Exception as e:
        print(f"⚠️  Could not build ICS: {e}")
        return None


# ── Email builder ────────────────────────────────────────────────────────────

def build_html(upcoming: dict, dt: datetime, gcal_url: str | None) -> str:
    opponent     = upcoming.get("opponent", "TBD")
    time_str     = upcoming.get("time", "--:--")[:5]
    venue        = upcoming.get("venue", "TBD")
    home_away    = (upcoming.get("home_away") or "").upper()
    display_date = format_display_date(dt)

    # Home / Away badge
    if home_away == "HOME":
        badge = '<span style="display:inline-block;background:#FF5C00;color:#fff;padding:4px 12px;border-radius:2px;font-family:Arial Black,Impact,Arial,sans-serif;font-size:11px;letter-spacing:2px;">HOME</span>'
    elif home_away == "AWAY":
        badge = '<span style="display:inline-block;background:#333;color:#aaa;padding:4px 12px;border-radius:2px;font-family:Arial Black,Impact,Arial,sans-serif;font-size:11px;letter-spacing:2px;">AWAY</span>'
    else:
        badge = ""

    # Google Calendar button
    gcal_btn = (
        f'<a href="{gcal_url}" target="_blank" style="'
        'display:inline-block;background:#FF5C00;color:#ffffff;text-decoration:none;'
        'padding:13px 26px;font-family:Arial Black,Impact,Arial,sans-serif;'
        'font-size:13px;letter-spacing:2px;border-radius:3px;margin-top:4px;">'
        '+ ADD TO GOOGLE CALENDAR</a>'
        if gcal_url else ""
    )

    opponent_safe = opponent.replace("&", "&amp;")

    return f"""<!DOCTYPE html>
<html lang="el">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Air Ballers — Επόμενος Αγώνας</title>
</head>
<body style="margin:0;padding:0;background:#111111;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#111111;padding:40px 0;">
  <tr><td align="center">
  <table width="580" cellpadding="0" cellspacing="0"
         style="max-width:580px;width:100%;border:1px solid #222;">

    <!-- ▌HEADER -->
    <tr>
      <td style="background:#0D0D0D;border-top:4px solid #FF5C00;padding:28px 36px 22px;">
        <p style="margin:0;font-family:Arial Black,Impact,Arial,sans-serif;font-size:10px;
                  letter-spacing:3px;color:#FF5C00;text-transform:uppercase;">{LEAGUE_NAME}</p>
        <h1 style="margin:6px 0 0;font-family:Arial Black,Impact,Arial,sans-serif;font-size:38px;
                   letter-spacing:5px;color:#FFFFFF;text-transform:uppercase;line-height:1;">
          AIR BALLERS 🏀
        </h1>
      </td>
    </tr>

    <!-- ▌NEXT GAME LABEL -->
    <tr>
      <td style="background:#FF5C00;padding:9px 36px;">
        <p style="margin:0;font-family:Arial Black,Impact,Arial,sans-serif;font-size:11px;
                  letter-spacing:3px;color:#fff;text-transform:uppercase;">▶&nbsp;&nbsp;NEXT GAME</p>
      </td>
    </tr>

    <!-- ▌MATCH CARD -->
    <tr>
      <td style="background:#161616;padding:32px 36px 28px;">

        <p style="margin:0 0 4px;font-family:Arial Black,Impact,Arial,sans-serif;font-size:12px;
                  letter-spacing:2px;color:#666666;text-transform:uppercase;">Air Ballers vs</p>
        <h2 style="margin:0 0 16px;font-family:Arial Black,Impact,Arial,sans-serif;font-size:42px;
                   letter-spacing:2px;color:#FF5C00;text-transform:uppercase;line-height:1.1;">
          {opponent_safe}
        </h2>

        {"<p style='margin:0 0 24px;'>" + badge + "</p>" if badge else "<p style='margin:0 0 24px;'></p>"}

        <!-- divider -->
        <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:26px;">
          <tr><td style="border-top:1px solid #2a2a2a;"></td></tr>
        </table>

        <!-- Details rows -->
        <table cellpadding="0" cellspacing="0">

          <tr>
            <td width="36" style="vertical-align:top;padding-bottom:18px;font-size:22px;">📅</td>
            <td style="vertical-align:top;padding-bottom:18px;padding-left:10px;">
              <p style="margin:0;font-family:Arial Black,Impact,Arial,sans-serif;font-size:10px;
                        letter-spacing:2px;color:#555;text-transform:uppercase;">Ημερομηνία</p>
              <p style="margin:5px 0 0;font-family:Arial Black,Impact,Arial,sans-serif;font-size:19px;
                        color:#ffffff;letter-spacing:1px;">{display_date}</p>
            </td>
          </tr>

          <tr>
            <td width="36" style="vertical-align:top;padding-bottom:18px;font-size:22px;">🕗</td>
            <td style="vertical-align:top;padding-bottom:18px;padding-left:10px;">
              <p style="margin:0;font-family:Arial Black,Impact,Arial,sans-serif;font-size:10px;
                        letter-spacing:2px;color:#555;text-transform:uppercase;">Ώρα</p>
              <p style="margin:5px 0 0;font-family:Arial Black,Impact,Arial,sans-serif;font-size:19px;
                        color:#ffffff;letter-spacing:1px;">{time_str}</p>
            </td>
          </tr>

          <tr>
            <td width="36" style="vertical-align:top;font-size:22px;">📍</td>
            <td style="vertical-align:top;padding-left:10px;">
              <p style="margin:0;font-family:Arial Black,Impact,Arial,sans-serif;font-size:10px;
                        letter-spacing:2px;color:#555;text-transform:uppercase;">Γήπεδο</p>
              <p style="margin:5px 0 0;font-family:Arial Black,Impact,Arial,sans-serif;font-size:19px;
                        color:#ffffff;letter-spacing:1px;">{venue}</p>
            </td>
          </tr>

        </table>
      </td>
    </tr>

    <!-- ▌CALENDAR SECTION -->
    <tr>
      <td style="background:#0D0D0D;padding:24px 36px;border-top:1px solid #222;">
        <p style="margin:0 0 14px;font-family:Arial,sans-serif;font-size:11px;
                  letter-spacing:1px;color:#666;text-transform:uppercase;">
          Πρόσθεσε τον αγώνα στο ημερολόγιό σου
        </p>
        {gcal_btn}
        <p style="margin:16px 0 0;font-family:Arial,sans-serif;font-size:11px;color:#444;line-height:1.6;">
          Ή άνοιξε το συνημμένο <strong style="color:#777;">.ics</strong> αρχείο
          για Apple Calendar, Outlook ή οποιοδήποτε άλλο ημερολόγιο.
        </p>
      </td>
    </tr>

    <!-- ▌VIEW SITE -->
    <tr>
      <td style="background:#0D0D0D;padding:0 36px 24px;border-top:0;">
        <a href="{SITE_URL}" style="font-family:Arial,sans-serif;font-size:12px;
                                     color:#FF5C00;text-decoration:none;letter-spacing:1px;">
          → Δες τη σελίδα της ομάδας
        </a>
      </td>
    </tr>

    <!-- ▌FOOTER -->
    <tr>
      <td style="background:#080808;padding:14px 36px;border-top:1px solid #1a1a1a;">
        <p style="margin:0;font-family:Arial,sans-serif;font-size:10px;
                  color:#333;letter-spacing:1px;text-transform:uppercase;">
          Air Ballers · Thessaloniki Amateur League · Auto-generated notification
        </p>
      </td>
    </tr>

  </table>
  </td></tr>
</table>
</body>
</html>"""


# ── Send ─────────────────────────────────────────────────────────────────────

def send_email(recipients: list[str], upcoming: dict, dt: datetime,
               gcal_url: str | None, ics_content: str | None) -> None:
    opponent = upcoming.get("opponent", "TBD")

    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"🏀 Air Ballers — Επόμενος Αγώνας vs {opponent}"
    msg["From"]    = SENDER_EMAIL
    msg["To"]      = ", ".join(recipients)

    msg.attach(MIMEText(build_html(upcoming, dt, gcal_url), "html", "utf-8"))

    if ics_content:
        filename = f"AirBallers_vs_{opponent.replace(' ', '_')}.ics"
        ics_part = MIMEBase("text", "calendar", method="PUBLISH", charset="UTF-8")
        ics_part.set_payload(ics_content.encode("utf-8"))
        encoders.encode_base64(ics_part)
        ics_part.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(ics_part)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, recipients, msg.as_string())

    print(f"✅  Email sent to {len(recipients)} recipient(s) — vs {opponent} on {upcoming.get('date')}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    data          = load_json(DATA_FILE)
    last_notified = load_json(LAST_NOTIFIED_FILE)
    recipients    = load_recipients()

    if not recipients:
        print("⚠️  recipients.txt is empty or missing — skipping.")
        return

    upcoming = data.get("upcoming")

    if not upcoming:
        print("ℹ️  No upcoming match in data.json — skipping.")
        return

    if not is_new_match(upcoming, last_notified):
        opponent = upcoming.get("opponent", "?")
        print(f"ℹ️  Match vs {opponent} already notified — skipping.")
        return

    dt = parse_datetime(upcoming)
    if not dt:
        print(f"⚠️  Could not parse match date/time: {upcoming.get('date')} {upcoming.get('time')} — skipping.")
        return

    print(f"🆕  New match: vs {upcoming.get('opponent')} on {upcoming.get('date')} at {upcoming.get('time')}")

    gcal_url    = build_gcal_url(upcoming, dt)
    ics_content = build_ics(upcoming, dt)

    send_email(recipients, upcoming, dt, gcal_url, ics_content)
    save_last_notified(upcoming)


if __name__ == "__main__":
    main()
