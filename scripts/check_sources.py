#!/usr/bin/env python3
"""Test that every registered source is reachable and that every college has at least one.

    scripts/check_sources.py            # human-readable report, exit 1 if a college has no reachable source
    scripts/check_sources.py --json     # machine-readable results (used by the daily routine)

Reads docs/sources.json: {"colleges": [...31 names...], "sources": [{college, name, kind, url, ...}]}.
Instagram and Facebook block plain HTTP clients, so those are reported as "social" and never fail the test;
the routine treats them as announcement locations to link to, not as pages it can read.
"""
import argparse, concurrent.futures, json, pathlib, sys, urllib.request, urllib.error
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 CambridgeBops/1.0"
SOCIAL = ("instagram.com", "facebook.com")


def probe(src, timeout=15):
    url = src["url"]
    if any(h in url for h in SOCIAL):
        return {**src, "status": "social", "code": None}
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(url, method=method, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return {**src, "status": "ok", "code": r.status, "final_url": r.geturl()}
        except urllib.error.HTTPError as e:
            if method == "HEAD" and e.code in (403, 405, 501):
                continue
            return {**src, "status": "blocked" if e.code in (401, 403, 429) else "fail", "code": e.code}
        except Exception as e:  # DNS, TLS, timeout
            if method == "HEAD":
                continue
            return {**src, "status": "fail", "code": None, "error": type(e).__name__}
    return {**src, "status": "fail", "code": None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--registry", default=str(ROOT / "docs" / "sources.json"))
    a = ap.parse_args()
    reg = json.loads(pathlib.Path(a.registry).read_text())
    colleges, sources = reg["colleges"], reg["sources"]

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        results = list(ex.map(probe, sources))

    by_college = {c: [] for c in colleges}
    by_college["All"] = []
    for r in results:
        by_college.setdefault(r["college"], []).append(r)

    missing = [c for c in colleges if not any(r["status"] in ("ok", "social") for r in by_college[c])]
    no_readable = [c for c in colleges if not any(r["status"] == "ok" for r in by_college[c])]
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total": len(results),
        "ok": sum(r["status"] == "ok" for r in results),
        "social": sum(r["status"] == "social" for r in results),
        "blocked": sum(r["status"] == "blocked" for r in results),
        "fail": sum(r["status"] == "fail" for r in results),
        "colleges_without_any_source": missing,
        "colleges_with_only_social_sources": [c for c in no_readable if c not in missing],
        "results": results,
    }
    if a.json:
        print(json.dumps(report, indent=1, ensure_ascii=False))
    else:
        for c in colleges + ["All"]:
            rows = by_college.get(c, [])
            flag = "  " if any(r["status"] == "ok" for r in rows) else ("!!" if c in missing else " ~")
            print(f"{flag} {c}: {len(rows)} source(s)")
            for r in rows:
                mark = {"ok": "✓", "social": "◦", "blocked": "⚠", "fail": "✗"}[r["status"]]
                code = f" {r['code']}" if r.get("code") else ""
                print(f"      {mark} {r['kind']:<14} {r['name']:<28} {r['url']}{code}")
        print(f"\n{report['ok']} reachable, {report['social']} social (not fetchable), {report['blocked']} blocked, {report['fail']} failing, of {report['total']}.")
        if missing:
            print("Colleges with NO working source: " + ", ".join(missing))
        if report["colleges_with_only_social_sources"]:
            print("Colleges with only Instagram/Facebook: " + ", ".join(report["colleges_with_only_social_sources"]))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
