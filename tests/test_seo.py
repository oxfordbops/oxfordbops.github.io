"""The deploy-time search additions: prerendered listings inside #list, a sitemap and robots.txt; the committed page carries the head tags."""
import datetime as dt, json, pathlib, shutil, subprocess, sys, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = (ROOT / "docs" / "index.html").read_text()
CITY = json.loads((ROOT / "city.json").read_text())


class TestSeo(unittest.TestCase):
    def test_head_tags(self):
        self.assertIn(f"<title>{CITY['name']} Bops:", PAGE)
        self.assertIn(f'<link rel="canonical" href="{CITY["site"]}">', PAGE)
        self.assertIn('"@type": "WebSite"', PAGE)
        self.assertIn('<meta name="description" content="' + CITY["name"] + " bops", PAGE)

    def test_deploy_additions(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp)
            shutil.copy(ROOT / "docs" / "index.html", out / "index.html")
            soon = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=2)).replace(microsecond=0).isoformat()
            past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)).replace(microsecond=0).isoformat()
            (out / "events.json").write_text(json.dumps({"generated": soon, "bops": [
                {"kind": "bop", "title": "Halloween <Bop>", "starts_at": soon, "college": CITY["colleges"][0] if isinstance(CITY["colleges"], list) else next(iter(CITY["colleges"]))},
                {"kind": "formal", "title": "Gone", "starts_at": past}]}))
            r = subprocess.run([sys.executable, str(ROOT / "scripts" / "seo.py"), str(out)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            page = (out / "index.html").read_text()
            self.assertIn("Halloween &lt;Bop&gt;", page)
            self.assertNotIn("Gone", page)
            self.assertIn("<loc>" + CITY["site"], (out / "sitemap.xml").read_text())
            self.assertIn("Sitemap: " + CITY["site"], (out / "robots.txt").read_text())


if __name__ == "__main__":
    unittest.main()
