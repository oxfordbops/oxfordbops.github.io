"""Browser test of every filter combination on the real page, with a fixed clock and generated data.

Runs when Python Playwright and its Chromium are installed (CI installs them); skipped otherwise.
For each tab (bops, formals, balls), every When option the tab offers, both formal types and every college chip,
it checks that the listed items are exactly the expected ones, that the count line agrees, and that switching tabs
neither carries filters over nor loses them.
"""
import datetime as dt, functools, http.server, json, os, pathlib, re, socketserver, tempfile, threading, unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SLUG = json.loads((ROOT / "city.json").read_text())["slug"]
TERMS = re.search(r'TERMS_VERSION = "([^"]+)"', (ROOT / "scripts" / "build.py").read_text()).group(1)
FORMALS = bool(json.loads((ROOT / "site" / "features.json").read_text()).get("formals"))
KINDS_ON = ["bop"] + (["formal"] if FORMALS else []) + ["ball", "society", "other"]
ACCEPTED = "try { localStorage.setItem(%r, %r); } catch (e) {}" % (SLUG + ".terms", TERMS)   # the filter tests start past the terms dialog
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

CLOCK_ISO = "2026-11-04T12:00:00Z"   # a Wednesday in term, GMT
TODAY = dt.date(2026, 11, 4)
CLOCK = """<script>(function(){const R=Date;const FIXED=new R("%s").getTime();const OFF=FIXED-R.now();
class D extends R{constructor(...a){if(a.length===0){super(R.now()+OFF)}else{super(...a)}}static now(){return R.now()+OFF}}
window.Date=D;})();</script>\n""" % CLOCK_ISO


def make_data(colleges):
    """Entries of each kind spread over the fortnight and over three colleges plus one outside any college."""
    cols = colleges[:3]
    bops = []
    for i in range(15):
        day = TODAY + dt.timedelta(days=i)
        for j, col in enumerate(cols + [None]):
            if (i + j) % 2:
                continue
            bops.append({"kind": "bop", "title": f"Bop {i}-{j}", "starts_at": f"{day}T21:00:00+00:00", "college": col,
                         "venue": "Bar", "url": "https://example.org/b", "source": "s"})
            bops.append({"kind": "formal", "special": bool(j % 2), "title": f"Formal {i}-{j}", "starts_at": f"{day}T19:30:00+00:00",
                         "college": col, "venue": "Hall", "url": "https://example.org/f", "source": "s"})
            if (i + j) % 3 == 0:
                bops.append({"kind": "society", "society": ["Union", "Footlights", "Hindu Society", None][j], "title": f"Talk {i}-{j}",
                             "starts_at": f"{day}T19:00:00+00:00", "college": None, "url": "https://example.org/s", "source": "s"})
                if bops[-1]["society"] is None:
                    del bops[-1]["society"]
            if (i + j) % 4 == 0:
                bops.append({"kind": "other", "title": f"Quiz {i}-{j}", "starts_at": f"{day}T18:00:00+00:00",
                             "college": col, "venue": "Bar", "url": "https://example.org/o", "source": "s"})
    for k, col in enumerate(cols):
        day = dt.date(2027, 6, 20 + k)
        bops.append({"kind": "ball", "title": f"Ball {k}", "starts_at": f"{day}T21:00:00+01:00", "college": col,
                     "url": "https://example.org/m", "source": "s"})
    bops.sort(key=lambda b: b["starts_at"])
    return {"generated": CLOCK_ISO, "run": {}, "sources": [{"slug": "s", "name": "S", "kind": "JCR site", "url": "https://example.org/", "ok": True, "found": 0}], "bops": bops}


def when_range(w):
    dow = TODAY.weekday()            # Mon 0
    to_sun = 6 - dow
    d = lambda n: TODAY + dt.timedelta(days=n)
    return {"all": (d(0), d(14)), "tonight": (d(0), d(0)), "today": (d(0), d(0)), "tomorrow": (d(1), d(1)),
            "weekend": (d(max(0, to_sun - 2)), d(to_sun)), "thisweek": (d(0), d(to_sun)), "nextweek": (d(to_sun + 1), d(to_sun + 7))}[w]


def expected(data, kind, when, college, ftype):
    out = []
    for b in data["bops"]:
        if b["kind"] != kind:
            continue
        day = dt.date.fromisoformat(b["starts_at"][:10])
        if kind != "ball":
            lo, hi = when_range(when)
            if not lo <= day <= hi:
                continue
        if kind == "formal" and ftype == "special" and not b["special"]:
            continue
        col = (b.get("society") if kind == "society" else b["college"]) or "none"
        if college != "all" and col != college:
            continue
        out.append((col, str(day)))
    return sorted(out)


WHEN_FOR = {"bop": ["all", "tonight", "tomorrow", "weekend", "nextweek"], "formal": ["all", "today", "tomorrow", "thisweek", "nextweek"], "ball": ["all"],
            "other": ["all", "today", "tomorrow", "weekend", "nextweek"], "society": ["all", "today", "tomorrow", "weekend", "nextweek"]}


@unittest.skipIf(sync_playwright is None and not os.environ.get("CI"), "Python Playwright not installed")
class TestFilters(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        city = json.loads((ROOT / "city.json").read_text())
        cls.colleges = list(city["colleges"])
        cls.data = make_data(cls.colleges)
        cls.tmp = tempfile.TemporaryDirectory()
        site = pathlib.Path(cls.tmp.name)
        page = (ROOT / "docs" / "index.html").read_text().replace("<head>", "<head>\n" + CLOCK, 1)
        (site / "index.html").write_text(page)
        (site / "events.json").write_text(json.dumps(cls.data))
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
        handler.log_message = lambda *a: None
        cls.httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}/"
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as e:
            cls.pw.stop(); cls.httpd.shutdown(); cls.tmp.cleanup()
            if os.environ.get("CI"):   # in CI a missing browser is a failure, not a skip
                raise
            raise unittest.SkipTest(f"Chromium not available: {e}")
        # Map tiles are not needed and must not slow the test down.
        cls.ctx = cls.browser.new_context()
        cls.ctx.add_init_script(ACCEPTED)
        cls.ctx.route("**/tile.openstreetmap.org/**", lambda r: r.abort())
        cls.ctx.route("**/gc.zgo.at/**", lambda r: r.abort())

    @classmethod
    def tearDownClass(cls):
        cls.browser.close(); cls.pw.stop(); cls.httpd.shutdown(); cls.httpd.server_close(); cls.tmp.cleanup()

    def open(self, query=""):
        p = self.ctx.new_page()
        errors = []
        p.on("pageerror", lambda e: errors.append(str(e)))
        p.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Content Security Policy" in m.text else None)
        p.goto(self.base + query)
        p.wait_for_selector("#list li, #list .empty", timeout=10000)
        return p, errors

    def count_line(self, p):
        return p.inner_text("#result strong") if p.is_visible("#result strong") else "0"

    def click(self, p, selector):
        p.click(selector)
        p.wait_for_timeout(30)

    def show_all(self, p):
        while p.is_visible("#more"):
            p.click("#more"); p.wait_for_timeout(20)

    def assert_view(self, p, kind, when, college, ftype, msg):
        exp = expected(self.data, kind, when, college, ftype)
        self.show_all(p)
        got = sorted(tuple(x) for x in p.eval_on_selector_all("#list li", "els => els.map(e => [e.dataset.college, e.dataset.day, e.dataset.kind])"))
        self.assertTrue(all(g[2] == kind for g in got), f"{msg}: another kind listed")
        self.assertEqual([g[:2] for g in got], exp, msg)
        if exp:
            self.assertTrue(self.count_line(p).startswith(str(len(exp)) + " "), f"{msg}: count line {self.count_line(p)!r}")

    def test_every_combination(self):
        p, errors = self.open()
        checked = 0
        for kind in KINDS_ON:
            cols = ["all"] + (["Union", "Footlights", "Hindu Society"] if kind == "society" else self.colleges[:3]) + ["none"]
            self.click(p, f'#kind button[data-kind="{kind}"]')
            for ftype in (["all", "special"] if kind == "formal" else ["all"]):
                if kind == "formal":
                    self.click(p, f'#ftype button[data-ftype="{ftype}"]')
                for when in WHEN_FOR[kind]:
                    if kind != "ball":
                        self.click(p, f'#when button[data-when="{when}"]')
                    for col in cols:
                        chip = p.query_selector(f'#chips [data-college="{col}"]')
                        if chip is None or not chip.is_visible():   # a college with nothing in this view has no chip; it must list nothing
                            self.assertEqual(expected(self.data, kind, when, col, ftype), [], f"{kind}/{when}/{col}/{ftype}: entries but no chip")
                            continue
                        if chip.get_attribute("aria-pressed") != "true":
                            chip.click(); p.wait_for_timeout(30)
                        self.assert_view(p, kind, when, col, ftype, f"{kind}/{when}/{col}/{ftype}")
                        checked += 1
                    if p.is_visible('#chips [data-college="all"]'):
                        self.click(p, '#chips [data-college="all"]')
        self.assertGreater(checked, 40)
        self.assertEqual(errors, [])

    def test_tabs_keep_their_own_filters(self):
        p, errors = self.open()
        col = self.colleges[0]
        self.click(p, '#when button[data-when="weekend"]')
        self.click(p, f'#chips [data-college="{col}"]')
        self.assert_view(p, "bop", "weekend", col, "all", "bops after filtering")
        # The second tab starts clean, not with the bop filters.
        second, ft = ("formal", "special") if FORMALS else ("society", "all")
        self.click(p, f'#kind button[data-kind="{second}"]')
        self.assert_view(p, second, "all", "all", "all", "second tab after switching")
        self.assertEqual(p.get_attribute('#when button[data-when="all"]', "aria-pressed"), "true")
        if FORMALS:
            self.click(p, '#ftype button[data-ftype="special"]')
        self.click(p, '#when button[data-when="today"]')
        # Balls start clean and hide the When row.
        self.click(p, '#kind button[data-kind="ball"]')
        self.assertFalse(p.is_visible("#when-group"))
        self.assert_view(p, "ball", "all", "all", "all", "balls after switching")
        # Going back restores each tab's own filters.
        self.click(p, '#kind button[data-kind="bop"]')
        self.assert_view(p, "bop", "weekend", col, "all", "bops restored")
        self.click(p, f'#kind button[data-kind="{second}"]')
        self.assert_view(p, second, "today", "all", ft, "second tab restored")
        # Other events start clean too.
        self.click(p, '#kind button[data-kind="other"]')
        self.assertTrue(p.is_visible("#when-group"))
        self.assert_view(p, "other", "all", "all", "all", "other after switching")
        self.assertEqual(errors, [])

    def test_links_and_clear(self):
        col = self.colleges[1]
        if FORMALS:
            p, errors = self.open(f"?kind=formal&formals=special&when=thisweek&college={col}")
            self.assert_view(p, "formal", "thisweek", col, "special", "from link")
            self.assertIn("formals=special", p.url)
            self.click(p, "#clear")
            self.assert_view(p, "formal", "all", "all", "all", "after clear")
            self.assertEqual(p.get_attribute('#ftype button[data-ftype="all"]', "aria-pressed"), "true", "clear resets the formal type")
        else:
            p, errors = self.open(f"?kind=other&when=weekend&college={self.colleges[0]}")
            self.assert_view(p, "other", "weekend", self.colleges[0], "all", "from link")
            self.click(p, "#clear")
            self.assert_view(p, "other", "all", "all", "all", "after clear")
        # An option that belongs to another tab is ignored, not carried.
        p2, _ = self.open("?kind=ball&when=tonight")
        self.assert_view(p2, "ball", "all", "all", "all", "ball link with a bop-only when")
        p3, _ = self.open()
        self.assertEqual(p3.get_attribute('#kind button[data-kind="bop"]', "aria-pressed"), "true", "Bops is the default tab")
        self.assertEqual(errors, [])


    def test_society_tab(self):
        """Societies group by society, hide the map, and a link with ?kind=society&society=X opens that society."""
        p, errors = self.open("?kind=society&society=Footlights")
        self.assert_view(p, "society", "all", "Footlights", "all", "society link")
        self.assertIn("society=Footlights", p.url)
        self.assertEqual(p.text_content("#college-lbl"), "Society")
        self.assertFalse(p.is_visible("#map"))
        self.click(p, '#kind button[data-kind="bop"]')
        self.assertTrue(p.is_visible("#map"))
        self.assertEqual(p.text_content("#college-lbl"), "College")
        self.assertEqual(errors, [])

    def test_terms_must_be_accepted(self):
        """A first visit shows the terms dialog; the page is inert until the box is ticked and Agree pressed; the choice is remembered."""
        ctx = self.browser.new_context(viewport={"width": 360, "height": 700}, is_mobile=True, has_touch=True)
        ctx.route("**/tile.openstreetmap.org/**", lambda r: r.abort())
        p = ctx.new_page(); errors = []
        p.on("pageerror", lambda e: errors.append(str(e)))
        p.goto(self.base); p.wait_for_selector("#list li, #list .empty", timeout=10000)
        self.assertTrue(p.is_visible("#terms-gate"))
        self.assertTrue(p.evaluate("document.querySelector('main').inert"), "the page is inert behind the dialog")
        self.assertTrue(p.is_disabled("#terms-ok"))
        self.assertIn("terms/", p.get_attribute("#terms-gate a", "href"))
        p.tap("#terms-check"); p.tap("#terms-ok")
        self.assertFalse(p.is_visible("#terms-gate"))
        self.assertFalse(p.evaluate("document.querySelector('main').inert"))
        p.reload(); p.wait_for_selector("#list li, #list .empty", timeout=10000)
        self.assertFalse(p.is_visible("#terms-gate"), "accepted once, not asked again")
        self.assertEqual(errors, [])
        ctx.close()

    @unittest.skipIf(FORMALS, "formals are switched on")
    def test_formals_paused(self):
        """With formals paused there is no Formals tab, a formals link opens Bops, and no formal is listed anywhere."""
        p, errors = self.open("?kind=formal&formals=special")
        self.assertIsNone(p.query_selector('#kind button[data-kind="formal"]'))
        self.assertEqual(p.get_attribute('#kind button[data-kind="bop"]', "aria-pressed"), "true")
        for k in KINDS_ON:
            self.click(p, f'#kind button[data-kind="{k}"]')
            self.assertEqual(p.eval_on_selector_all('#list li[data-kind="formal"]', "e => e.length"), 0, k)
            self.assertFalse(any(t.startswith("Formal ") for t in p.eval_on_selector_all("#list li .name", "e => e.map(x => x.textContent)")), k)
        self.assertFalse(p.is_visible("#type-group"))
        self.assertEqual(errors, [])

    def test_pagination(self):
        """A long list shows 25 at first; Show more adds 25; changing a filter starts again at 25."""
        pk = "formal" if FORMALS else "bop"
        p, errors = self.open(f"?kind={pk}")
        total = len(expected(self.data, pk, "all", "all", "all"))
        self.assertGreater(total, 25)
        self.assertEqual(p.eval_on_selector_all("#list li", "els => els.length"), 25)
        self.assertTrue(p.inner_text("#more").startswith(f"Show {min(25, total - 25)} more"), p.inner_text("#more"))
        self.click(p, "#more")
        self.assertEqual(p.eval_on_selector_all("#list li", "els => els.length"), min(50, total))
        self.click(p, '#when button[data-when="tomorrow"]')
        self.click(p, '#when button[data-when="all"]')
        self.assertEqual(p.eval_on_selector_all("#list li", "els => els.length"), 25)
        self.assertEqual(errors, [])

    def test_mobile(self):
        """On a 320px touch phone, in every tab: no sideways scroll, tap targets at least 40px tall, no text under 12px."""
        ctx = self.browser.new_context(viewport={"width": 320, "height": 640}, is_mobile=True, has_touch=True, device_scale_factor=2)
        ctx.add_init_script(ACCEPTED)
        ctx.route("**/tile.openstreetmap.org/**", lambda r: r.abort())
        p = ctx.new_page(); errors = []
        p.on("pageerror", lambda e: errors.append(str(e)))
        p.goto(self.base + "?college=" + self.colleges[0]); p.wait_for_selector("#list li, #list .empty", timeout=10000)
        for kind in KINDS_ON:
            p.tap(f'#kind button[data-kind="{kind}"]'); p.wait_for_timeout(50)
            r = p.evaluate("""() => {
              const W = document.documentElement.clientWidth, out = {scroll: document.documentElement.scrollWidth - W, small: [], tiny: []};
              for (const el of document.querySelectorAll('main *')) {
                const b = el.getBoundingClientRect(), cs = getComputedStyle(el);
                if (!b.width || el.closest('#map, .leaflet-container')) continue;
                if (el.matches('button') && b.height < 40) out.small.push(el.textContent.trim().slice(0, 20) + ' ' + Math.round(b.height));
                if ([...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()) && parseFloat(cs.fontSize) < 12) out.tiny.push(el.textContent.trim().slice(0, 20));
              }
              return out; }""")
            self.assertLessEqual(r["scroll"], 0, f"{kind}: page scrolls sideways")
            self.assertEqual(r["small"], [], f"{kind}: tap targets under 40px")
            self.assertEqual(r["tiny"], [], f"{kind}: text under 12px")
        self.assertEqual(errors, [])
        ctx.close()

    def test_running_event_stays_until_its_end(self):
        """At 02:00 a ball that started at 21:00 and ends at 06:00 is still listed; one that ended at 01:00 is not."""
        data = {"generated": "2026-11-05T02:00:00Z", "run": {}, "sources": [{"slug": "s", "name": "S", "kind": "JCR site", "url": "https://example.org/", "ok": True, "found": 0}],
                "bops": [{"kind": "bop", "title": "Late bop", "starts_at": "2026-11-04T21:00:00+00:00", "ends_at": "2026-11-05T06:00:00+00:00", "college": self.colleges[0], "url": "https://example.org/a", "source": "s"},
                         {"kind": "bop", "title": "Early bop", "starts_at": "2026-11-04T20:00:00+00:00", "ends_at": "2026-11-05T01:00:00+00:00", "college": self.colleges[1], "url": "https://example.org/b", "source": "s"}]}
        site = pathlib.Path(self.tmp.name)
        clock = CLOCK.replace(CLOCK_ISO, "2026-11-05T02:00:00Z")
        (site / "late.html").write_text((ROOT / "docs" / "index.html").read_text().replace("<head>", "<head>\n" + clock, 1).replace('fetch("events.json"', 'fetch("late.json"'))
        (site / "late.json").write_text(json.dumps(data))
        p = self.ctx.new_page(); p.goto(self.base + "late.html"); p.wait_for_selector("#list li, #list .empty", timeout=10000)
        titles = p.eval_on_selector_all("#list li .name", "els => els.map(e => e.textContent)")
        self.assertTrue(any("Late bop" in t for t in titles), titles)
        self.assertFalse(any("Early bop" in t for t in titles), titles)


if __name__ == "__main__":
    unittest.main()
