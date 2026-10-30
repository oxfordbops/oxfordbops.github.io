"""The page is a single file; these checks catch the ways a hand edit breaks it."""
import json, pathlib, re, subprocess, sys, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = (ROOT / "docs" / "index.html").read_text()
SCRIPT = PAGE.split("<script>")[1].split("</script>")[0]


class TestPage(unittest.TestCase):
    def test_script_parses(self):
        r = subprocess.run(["node", "-e", "new Function(require('fs').readFileSync(0,'utf8'))"], input=SCRIPT, text=True, capture_output=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_required_elements(self):
        for id_ in ["when", "chips", "result", "map", "list", "lastrun"]:
            self.assertIn(f'id="{id_}"', PAGE, id_)

    def test_reads_events_json_only(self):
        self.assertIn('fetch("events.json"', SCRIPT)
        for banned in ["supabase", "Add a bop", "<form", "<dialog", "/issues/new"]:
            self.assertNotIn(banned.lower(), PAGE.lower(), banned)

    def test_college_coordinates_match_registry(self):
        city = json.loads((ROOT / "city.json").read_text())
        reg = json.loads((ROOT / "docs" / "sources.json").read_text())
        names = re.findall(r'"([^"]+)": \[5\d\.\d+, [-\d.]+\]', SCRIPT)
        self.assertEqual(sorted(names), sorted(reg["colleges"]))
        self.assertEqual(sorted(names), sorted(city["colleges"]))
        (lat0, lat1), (lng0, lng1) = city["bbox"]["lat"], city["bbox"]["lng"]
        for lat, lng in re.findall(r"\[(5\d\.\d+), ([-\d.]+)\]", SCRIPT):
            self.assertTrue(lat0 < float(lat) < lat1 and lng0 < float(lng) < lng1, (lat, lng))

    def test_rendered_pages_are_up_to_date(self):
        # docs/index.html and docs/ROUTINE.md are generated from site/ and city.json; a stale build must not deploy.
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "build.py"), "--check"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_page_names_the_city(self):
        city = json.loads((ROOT / "city.json").read_text())
        self.assertIn(f"<title>{city['name']} Bops</title>", PAGE)
        self.assertIn(city["tagline"], PAGE)

    def test_external_resources_are_pinned_and_allowed(self):
        srcs = re.findall(r'(?:src|href)="(https://[^"]+)"', PAGE.split("<script>")[0])
        for u in srcs:
            self.assertTrue(u.startswith(("https://fonts.googleapis.com", "https://fonts.gstatic.com", "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/", "https://gc.zgo.at/count.js")), u)
        self.assertIn("tile.openstreetmap.org", SCRIPT)
        self.assertNotIn("cartocdn", SCRIPT)

    def test_analytics_follow_city_json(self):
        # The GoatCounter snippet is present exactly when city.json names a site code; the page never sends anything else.
        code = (json.loads((ROOT / "city.json").read_text()).get("analytics") or {}).get("goatcounter", "")
        head = PAGE.split("<script>")[0]
        if code:
            self.assertIn(f'data-goatcounter="https://{code}.goatcounter.com/count"', head)
            self.assertIn('async src="https://gc.zgo.at/count.js"', head)
        else:
            self.assertNotIn("goatcounter", PAGE.lower())
        self.assertIn("window.goatcounter && window.goatcounter.count", SCRIPT)
        self.assertNotIn("googletagmanager", PAGE.lower())

    def test_theme_tokens_defined_in_both_themes(self):
        tokens = set(re.findall(r"(--[a-z-]+):", PAGE.split("@media")[0]))
        dark = PAGE.split(':root[data-theme="dark"]')[1].split("}")[0]
        for t in ["--bg", "--fg", "--muted", "--rule", "--cam", "--cam-ink", "--cam-tint", "--accent", "--field"]:
            self.assertIn(t, tokens)
            self.assertIn(t + ":", dark, f"{t} missing in dark theme")

    def test_links_and_entries_are_guarded(self):
        # Only http(s) URLs become hrefs, entries without a title or a parseable start are dropped,
        # and every string from the data file passes through the escaper before reaching innerHTML.
        self.assertIn("function safeUrl(u)", SCRIPT)
        self.assertIn('/^https?:\\/\\//i.test(u)', SCRIPT)
        self.assertIn('typeof e.title !== "string"', SCRIPT)
        self.assertNotIn("+ e.title +", SCRIPT)
        self.assertNotIn("+ e.venue +", SCRIPT)
        self.assertNotIn("+ e.details +", SCRIPT)

    def test_dates_are_rendered_in_cambridge_time(self):
        self.assertIn('TZ = "Europe/London"', SCRIPT)
        self.assertNotIn("toLocaleDateString()", SCRIPT)


if __name__ == "__main__":
    unittest.main()
