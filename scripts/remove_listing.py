#!/usr/bin/env python3
"""Remove one listing from docs/events.json, safely: matched by its exact start and title, source counts kept consistent.

    python3 scripts/remove_listing.py --start 2026-11-05T19:30 --title "Diwali Formal" --reason "cancelled on the source page"

Prints the removed entry as one JSON line with the reason, for the daily check's report. Exit 2 if nothing or more than
one entry matches (nothing is changed then). Never adds or edits listings.
"""
import argparse, json, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="the entry's starts_at, at least to the minute (2026-11-05T19:30)")
    ap.add_argument("--title", required=True, help="the entry's exact title")
    ap.add_argument("--reason", required=True)
    a = ap.parse_args()
    p = ROOT / "docs" / "events.json"; text = p.read_text()
    indent = len(text.split("\n", 1)[1]) - len(text.split("\n", 1)[1].lstrip(" ")) if "\n" in text else 1
    d = json.loads(text)
    hits = [b for b in d["bops"] if b.get("starts_at", "").startswith(a.start) and b.get("title") == a.title]
    if len(hits) != 1:
        print(f"{len(hits)} entries match; nothing removed", file=sys.stderr); sys.exit(2)
    d["bops"].remove(hits[0])
    if isinstance(d.get("sources"), list):
        for s in d["sources"]:
            s["found"] = sum(1 for b in d["bops"] if b.get("source") == s["slug"])
    p.write_text(json.dumps(d, indent=indent or 1, ensure_ascii=False) + "\n")
    print(json.dumps({"removed": hits[0], "reason": a.reason}, ensure_ascii=False))


if __name__ == "__main__":
    main()
