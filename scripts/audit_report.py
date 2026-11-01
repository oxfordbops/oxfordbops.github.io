#!/usr/bin/env python3
"""Turn the two-monthly audit's JSON into a GitHub issue labeled "audit" and print one summary line.

    python3 scripts/audit_report.py /tmp/audit.json [--dry-run]

Validates the file against scripts/audit_schema.json (required keys, types, enums), formats the findings,
and opens an issue or comments on the open one with `gh api`. Low-confidence finds are listed but never
raise an issue on their own. If the issue cannot be opened it prints "ISSUE FAILED" and the report.
Stdlib only.
"""
import json, pathlib, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "scripts" / "audit_schema.json").read_text())
TYPES = {"object": dict, "array": list, "string": str, "integer": int}


def check(value, schema, where="audit"):
    """Return a list of problems; empty means valid."""
    t = schema.get("type")
    if t and not (isinstance(value, TYPES[t]) and not (t == "integer" and isinstance(value, bool))):
        return [f"{where}: expected {t}"]
    errs = []
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{where}: {value!r} not in {schema['enum']}")
    if t == "object":
        props = schema.get("properties", {})
        errs += [f"{where}: missing {k}" for k in schema.get("required", []) if k not in value]
        if schema.get("additionalProperties") is False:
            errs += [f"{where}: unexpected {k}" for k in value if k not in props]
        for k, v in value.items():
            if k in props:
                errs += check(v, props[k], f"{where}.{k}")
    if t == "array":
        for i, v in enumerate(value):
            errs += check(v, schema.get("items", {}), f"{where}[{i}]")
    return errs


def report(a, city):
    sure = [m for m in a["missing"] if m["confidence"] != "low"]
    low = [m for m in a["missing"] if m["confidence"] == "low"]
    counts = {"missing": len(sure), "low confidence": len(low), "mismatched": len(a["mismatched"]), "registry": len(a["registry"]),
              "new sources": len(a["new_sources"]), "term dates": len(a["term_dates"]), "unreadable": len(a["unreadable_sources"])}
    summary = f"{city} Bops audit {a['checked_at'][:10]}: " + ", ".join(f"{v} {k}" for k, v in counts.items())
    act = bool(sure or a["mismatched"] or a["registry"] or a["new_sources"] or a["term_dates"])
    L = [f"Audit of {city} Bops, window {a['window_from']} to {a['window_to']}, {a['sources_checked']} sources read.", ""]
    def section(title, rows):
        if rows:
            L.extend(["", f"## {title}", ""] + rows)
    section("Found on a source but not listed", [f"- **{m['college']}** {m['kind']}: {m['title']}, {m['date']} {m['time']} ({m['confidence']}) - {m['url']}\n  {m['evidence']}" for m in sure + low])
    section("Listed, but the source says otherwise", [f"- **{m['college']}** {m['kind']}: {m['title']}, {m['date']}: listed {m['listed']}; source says {m['source_says']} - {m['url']}" for m in a["mismatched"]])
    section("Registry: sources or schedules to fix", [f"- **{r['college']}**: {r['problem']} - {r['url']}\n  {r['evidence']}" for r in a["registry"]])
    section("Sources to consider adding", [f"- **{s['college']}**: {s['name']} ({s['kind']}) - {s['url']}\n  {s['evidence']}" for s in a["new_sources"]])
    section("Term dates", [f"- {t['problem']}; official: {t['official']} - {t['url']}" for t in a["term_dates"]])
    section("Listed from Instagram, not checkable", [f"- {u['college']}: {u['title']}, {u['date']}" for u in a["unverifiable"]])
    section("Sources that could not be read", [f"- {u['url']}: {u['status']}" for u in a["unreadable_sources"]])
    return summary, "\n".join(L), act


def gh(*args, body=None):
    r = subprocess.run(["gh", "api", *args], input=body, capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise RuntimeError(r.stderr.strip()[:300])
    return json.loads(r.stdout) if r.stdout.strip() else None


def main():
    path = next((x for x in sys.argv[1:] if not x.startswith("--")), None)
    if not path:
        sys.exit("usage: audit_report.py /tmp/audit.json [--dry-run]")
    a = json.loads(pathlib.Path(path).read_text())
    errs = check(a, SCHEMA)
    if errs:
        print("INVALID " + "; ".join(errs[:10]))
        sys.exit(2)
    city = json.loads((ROOT / "city.json").read_text())
    repo = f"{city['org']}/{city['org']}.github.io"
    summary, body, act = report(a, city["name"])
    if "--dry-run" in sys.argv:
        print(summary); print(body); return
    try:
        gh(f"repos/{repo}/labels", "-f", "name=audit", "-f", "color=2A97C9", "-f", "description=Two-monthly audit findings") if not any(
            l["name"] == "audit" for l in gh(f"repos/{repo}/labels?per_page=100")) else None
        open_ = gh(f"repos/{repo}/issues?labels=audit&state=open")
        title = summary
        if open_:
            n = open_[0]["number"]
            gh(f"repos/{repo}/issues/{n}/comments", "--input", "-", body=json.dumps({"body": f"### {title}\n\n{body}"}))
            gh(f"repos/{repo}/issues/{n}", "-X", "PATCH", "-f", f"title={title}")
            url = open_[0]["html_url"]
        elif act:
            url = gh(f"repos/{repo}/issues", "--input", "-", body=json.dumps({"title": title, "body": body, "labels": ["audit"]}))["html_url"]
        else:
            url = "no issue: nothing to act on"
    except Exception as e:
        print(f"ISSUE FAILED ({e})"); print(summary); print(body)
        sys.exit(1)
    print(summary); print(url)


if __name__ == "__main__":
    main()
