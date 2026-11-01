#!/usr/bin/env python3
"""Move listings that have started before today (UK) out of docs/events.json into docs/archive/YYYY-MM.json.

    python3 scripts/archive.py              # the weekly routine runs this before reconciling
    python3 scripts/archive.py --from-git   # also recover every past entry ever committed (one-off backfill)

One file per month of the event, sorted by start, each entry at most once (same kind, college, start and title).
Balls stay in events.json until their day has passed, like everything else. Stdlib only.
"""
import datetime as dt, json, pathlib, subprocess, sys
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parent.parent
EVENTS, ARCHIVE = ROOT / "docs" / "events.json", ROOT / "docs" / "archive"
LONDON = ZoneInfo("Europe/London")


def day(e):
    return dt.datetime.fromisoformat(e["starts_at"].replace("Z", "+00:00")).astimezone(LONDON).date()


def key(e):
    return (e.get("kind", "bop"), e.get("college"), e["starts_at"], e["title"].strip().lower())


def from_git():
    """Every entry in every committed version of docs/events.json."""
    shas = subprocess.run(["git", "-C", str(ROOT), "log", "--format=%H", "--", "docs/events.json"], capture_output=True, text=True).stdout.split()
    for sha in reversed(shas):   # oldest first, so the latest version of an entry wins
        blob = subprocess.run(["git", "-C", str(ROOT), "show", f"{sha}:docs/events.json"], capture_output=True, text=True).stdout
        try:
            yield from json.loads(blob).get("bops", [])
        except (json.JSONDecodeError, AttributeError):
            continue


def main():
    today = dt.datetime.now(LONDON).date()
    data = json.loads(EVENTS.read_text())
    past = [e for e in data["bops"] if day(e) < today]
    if "--from-git" in sys.argv:
        past += [e for e in from_git() if "starts_at" in e and "title" in e and day(e) < today]
    by_month = {}
    for e in past:
        by_month.setdefault(day(e).strftime("%Y-%m"), []).append(e)
    ARCHIVE.mkdir(exist_ok=True)
    added = 0
    for month, entries in by_month.items():
        f = ARCHIVE / f"{month}.json"
        merged = {key(e): e for e in (json.loads(f.read_text()) if f.exists() else [])}
        before = len(merged)
        for e in entries:
            merged[key(e)] = e
        added += len(merged) - before
        f.write_text(json.dumps(sorted(merged.values(), key=lambda e: e["starts_at"]), indent=1, ensure_ascii=False) + "\n")
    keep = [e for e in data["bops"] if day(e) >= today]
    if len(keep) != len(data["bops"]):   # rewrite only when something moved, in the file's own indentation
        text = EVENTS.read_text()
        indent = len(text.split("\n", 1)[1]) - len(text.split("\n", 1)[1].lstrip(" ")) if "\n" in text else 1
        data["bops"] = keep
        EVENTS.write_text(json.dumps(data, indent=indent or 1, ensure_ascii=False) + "\n")
    print(f"archived {added} new past entries into {len(by_month)} month files; {len(keep)} remain listed")


if __name__ == "__main__":
    main()
