#!/usr/bin/env python3
"""
JD Gyms Bolton -> iCalendar feed.

Reads the 7-day class timetable from the public gym page, merges it with
classes seen on earlier runs (so the last few weeks stay visible), and writes:

  docs/jd-bolton-classes.ics   the calendar feed iCloud subscribes to
  docs/classes.json            state carried between runs

The timetable page is authoritative for the dates it shows: a class that
disappears from it (cancelled / moved) is removed from the feed too.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

GYM_URL = os.environ.get("GYM_URL", "https://www.jdgyms.co.uk/gym/bolton/")
GYM_NAME = os.environ.get("GYM_NAME", "JD Gyms Bolton")
GYM_ADDRESS = os.environ.get(
    "GYM_ADDRESS", "Unit 1, Morston Point, Manchester Rd, Bolton BL2 1HA"
)
KEEP_PAST_DAYS = int(os.environ.get("KEEP_PAST_DAYS", "28"))
OUT_DIR = Path(os.environ.get("OUT_DIR", "docs"))
ICS_NAME = "jd-bolton-classes.ics"
STATE_NAME = "classes.json"

LONDON = ZoneInfo("Europe/London")
NAME_RE = re.compile(r"^(?P<name>.*?)\s*\((?P<mins>\d+)\s*min[s]?\)\s*$", re.I)
TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --------------------------------------------------------------------------- fetch

def fetch(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
        ),
        "Accept-Language": "en-GB,en;q=0.9",
    }
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            r = requests.get(url, headers=headers, timeout=30)
            r.raise_for_status()
            return r.text
        except requests.RequestException as e:
            last_err = e
            time.sleep(5 * (attempt + 1))
    raise SystemExit(f"Could not fetch {url}: {last_err}")


# --------------------------------------------------------------------------- parse

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def parse_timetable(html: str) -> tuple[list[dict], list[str]]:
    """Return (classes, dates_covered). Raises if the timetable isn't found."""
    soup = BeautifulSoup(html, "html.parser")
    panels = soup.select('[data-class-timetable-target="panel"][data-panel]')
    if not panels:
        raise SystemExit(
            "Timetable panels not found on the page - the site layout may have "
            "changed. Feed left untouched."
        )

    classes: list[dict] = []
    dates: list[str] = []
    for panel in panels:
        day = panel.get("data-panel", "").strip()
        if not DATE_RE.match(day):
            continue
        dates.append(day)
        for tr in panel.select("tbody tr"):
            tds = tr.find_all("td")
            if len(tds) < 2:
                continue
            t = _clean(tds[0].get_text())
            if not TIME_RE.match(t):
                continue
            lines = [_clean(p.get_text()) for p in tds[1].find_all("p")]
            lines = [l for l in lines if l] or [
                l for l in (_clean(x) for x in tds[1].get_text("\n").split("\n")) if l
            ]
            if not lines:
                continue

            m = NAME_RE.match(lines[0])
            name = m.group("name") if m else lines[0]
            mins = int(m.group("mins")) if m else 45

            instructor, room = "", ""
            if len(lines) > 1:
                detail = lines[1]
                if "," in detail:
                    instructor, room = (x.strip() for x in detail.rsplit(",", 1))
                else:
                    instructor = detail
            instructor = instructor.rstrip(" .").strip()

            classes.append(
                {
                    "date": day,
                    "time": t.zfill(5),
                    "name": name,
                    "minutes": mins,
                    "instructor": instructor,
                    "room": room,
                }
            )
    if not dates:
        raise SystemExit("No dated timetable panels found. Feed left untouched.")
    return classes, sorted(dates)


# --------------------------------------------------------------------------- state

def uid_for(c: dict) -> str:
    key = f"{c['date']}|{c['time']}|{c['name'].lower()}"
    return hashlib.sha1(key.encode()).hexdigest()[:20] + "@jd-bolton-classes"


def merge(previous: dict, scraped: list[dict], covered: list[str], today: date) -> dict:
    window = set(covered)
    cutoff = (today - timedelta(days=KEEP_PAST_DAYS)).isoformat()
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    merged: dict[str, dict] = {}
    # Keep older classes that are outside the scraped window (history).
    for uid, c in previous.items():
        if c["date"] in window or c["date"] < cutoff:
            continue
        if c["date"] > max(covered):
            # Beyond what the page shows now - can't happen normally; drop it.
            continue
        merged[uid] = c

    for c in scraped:
        uid = uid_for(c)
        old = previous.get(uid)
        same = old and all(old.get(k) == c[k] for k in c)
        c = dict(c)
        c["stamp"] = old["stamp"] if same else now
        merged[uid] = c
    return dict(sorted(merged.items(), key=lambda kv: (kv[1]["date"], kv[1]["time"])))


# --------------------------------------------------------------------------- ics

def _esc(s: str) -> str:
    return (
        s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """Fold to 75 octets per RFC 5545."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts, cur = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        limit = 75 if not parts else 74
        if len(cur) + len(b) > limit:
            parts.append(cur.decode("utf-8"))
            cur = b""
        cur += b
    parts.append(cur.decode("utf-8"))
    return "\r\n ".join(parts)


def to_utc(day: str, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    local = datetime.fromisoformat(day).replace(hour=h, minute=m, tzinfo=LONDON)
    return local.astimezone(timezone.utc)


def build_ics(events: dict) -> str:
    fmt = "%Y%m%dT%H%M%SZ"
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//jd-bolton-classes//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_esc(GYM_NAME)} classes",
        "X-WR-CALDESC:Class timetable scraped from the JD Gyms website. No booking needed.",
        "X-WR-TIMEZONE:Europe/London",
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
        "X-PUBLISHED-TTL:PT6H",
    ]
    for uid, c in events.items():
        start = to_utc(c["date"], c["time"])
        end = start + timedelta(minutes=c["minutes"])
        location = f"{GYM_NAME}" + (f" – {c['room']}" if c["room"] else "")
        desc = [f"{c['name']} ({c['minutes']} min)"]
        if c["instructor"]:
            desc.append(f"Instructor: {c['instructor']}")
        if c["room"]:
            desc.append(f"Room: {c['room']}")
        desc += ["No booking needed - just turn up.", GYM_ADDRESS, GYM_URL]
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{c['stamp']}",
            f"LAST-MODIFIED:{c['stamp']}",
            f"DTSTART:{start.strftime(fmt)}",
            f"DTEND:{end.strftime(fmt)}",
            f"SUMMARY:{_esc(c['name'])}",
            f"LOCATION:{_esc(location)}",
            f"DESCRIPTION:{_esc(chr(10).join(desc))}",
            f"URL:{GYM_URL}",
            "CATEGORIES:Gym class",
            "TRANSP:TRANSPARENT",  # shows as free, so it doesn't block your schedule
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(l) for l in lines) + "\r\n"


# --------------------------------------------------------------------------- main

def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    state_path = OUT_DIR / STATE_NAME
    previous = json.loads(state_path.read_text()) if state_path.exists() else {}

    html = Path(sys.argv[1]).read_text() if len(sys.argv) > 1 else fetch(GYM_URL)
    scraped, covered = parse_timetable(html)

    today = datetime.now(LONDON).date()
    events = merge(previous, scraped, covered, today)

    state_path.write_text(json.dumps(events, indent=1, ensure_ascii=False) + "\n")
    (OUT_DIR / ICS_NAME).write_bytes(build_ics(events).encode("utf-8"))

    print(f"Timetable {covered[0]} -> {covered[-1]}: {len(scraped)} classes scraped, "
          f"{len(events)} in feed.")
    for c in scraped:
        print(f"  {c['date']} {c['time']}  {c['name']} ({c['minutes']}m) "
              f"{c['instructor']} / {c['room']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
