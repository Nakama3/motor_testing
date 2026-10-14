"""Offline tests: parsers against small hand-written pages, plus the
filtering / de-duplication logic. Run with: python -m unittest test_watch"""
import datetime as dt
import json
import tempfile
import tomllib
import unittest
from pathlib import Path

import run
from geo import commute_check, nearest_station
from sources import (Listing, generic_listings, parse_alert_email, parse_beds,
                     parse_craigslist, parse_price, zillow_result)

CFG = tomllib.loads((Path(__file__).parent / "config.toml").read_text())


def listing(**kw):
    base = dict(source="test", id="1", url="https://x/1", title="Nice place",
                price=1800, beds=1, baths=1, address="1 Main St", city="San Mateo")
    base.update(kw)
    return Listing(**base)


class Parsing(unittest.TestCase):
    def test_price_and_beds(self):
        self.assertEqual(parse_price("$1,950/mo"), 1950)
        self.assertEqual(parse_price("$1,800+ 1 bd"), 1800)
        self.assertEqual(parse_beds("Studio"), 0)
        self.assertEqual(parse_beds("1 bd"), 1)
        self.assertEqual(parse_beds("2"), 2)

    def test_craigslist(self):
        ld = {"itemListElement": [{"item": {"numberOfBedrooms": 1, "numberOfBathroomsTotal": 1,
                                            "latitude": 37.567, "longitude": -122.322,
                                            "address": {"addressLocality": "San Mateo"}}}]}
        html = f"""<script type="application/ld+json" id="ld_searchpage_results">{json.dumps(ld)}</script>
        <ol><li class="cl-static-search-result" title="Sunny 1BR near train">
          <a href="https://sfbay.craigslist.org/pen/apa/d/san-mateo-sunny/7801234567.html">
            <div class="title">Sunny 1BR near train</div>
            <div class="details"><div class="price">$1,895</div><div class="location"> san mateo </div></div>
          </a></li></ol>"""
        [l] = parse_craigslist(html)
        self.assertEqual((l.id, l.price, l.beds, l.city), ("7801234567", 1895, 1, "San Mateo"))
        self.assertAlmostEqual(l.lat, 37.567)

    def test_zillow_building_units(self):
        r = {"zpid": "99", "detailUrl": "/b/some-apts/", "buildingName": "Some Apts",
             "address": "100 El Camino Real, San Carlos, CA", "addressCity": "San Carlos",
             "latLong": {"latitude": 37.506, "longitude": -122.26},
             "units": [{"price": "$1,750+", "beds": "0"}, {"price": "$2,300+", "beds": "1"}]}
        units = zillow_result(r)
        self.assertEqual([(u.price, u.beds) for u in units], [(1750, 0), (2300, 1)])
        self.assertTrue(units[0].url.startswith("https://www.zillow.com/b/"))

    def test_generic_json_ld(self):
        blob = {"@type": "ItemList", "itemListElement": [
            {"@type": "Apartment", "name": "Garden studio", "url": "/apartments/abc123",
             "address": {"streetAddress": "5 Elm St", "addressLocality": "Burlingame"},
             "geo": {"latitude": "37.58", "longitude": "-122.345"},
             "offers": {"price": "1650"}, "numberOfBedrooms": 0}]}
        html = f'<script type="application/ld+json">{json.dumps(blob)}</script>'
        [l] = generic_listings(html, "zumper", "https://www.zumper.com")
        self.assertEqual((l.price, l.beds, l.city, l.url),
                         (1650, 0, "Burlingame", "https://www.zumper.com/apartments/abc123"))

    def test_alert_email(self):
        html = """<table><tr><td><a href="https://www.zillow.com/homedetails/1-Oak-St/123_zpid/?utm=x">1 Oak St</a>
                  <p>$1,900/mo · 1 bd · 1 ba · Redwood City, CA</p></td></tr></table>"""
        [l] = parse_alert_email(html)
        self.assertEqual((l.price, l.beds, l.baths), (1900, 1, 1))
        self.assertEqual(l.url, "https://www.zillow.com/homedetails/1-Oak-St/123_zpid/")


class Filtering(unittest.TestCase):
    def test_criteria(self):
        c = CFG["criteria"]
        self.assertTrue(run.fits_criteria(listing(), c))
        self.assertTrue(run.fits_criteria(listing(beds=0), c))        # studio ok
        self.assertFalse(run.fits_criteria(listing(price=2100), c))
        self.assertFalse(run.fits_criteria(listing(beds=2), c))
        self.assertFalse(run.fits_criteria(listing(price=None), c))

    def test_commute(self):
        loc = CFG["location"]
        near_station = listing(lat=37.7780, lon=-122.3960)   # by 4th & King
        oakland = listing(lat=37.8044, lon=-122.2712, city="Oakland")
        no_pin_ok = listing(city="Menlo Park")
        no_pin_far = listing(city="Daly City")
        self.assertTrue(commute_check(near_station, loc)[0])
        self.assertFalse(commute_check(oakland, loc)[0])
        self.assertTrue(commute_check(no_pin_ok, loc)[0])
        self.assertFalse(commute_check(no_pin_far, loc)[0])
        self.assertEqual(nearest_station((37.4856, -122.232))[0], "Redwood City")


class DailyRun(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self._orig = run.STATE, run.REPORTS
        run.STATE, run.REPORTS = tmp / "seen.json", tmp / "reports"

    def tearDown(self):
        run.STATE, run.REPORTS = self._orig

    def test_only_new_listings_then_price_drop(self):
        day1, day2 = dt.date(2026, 10, 14), dt.date(2026, 10, 15)
        a = listing(id="a", address="1 Main St")
        dup = listing(source="other", id="z", address="1 Main St")   # same unit, other site
        _, report = run.run(CFG, day1, listings=[a, dup], status={"test": "ok"})
        self.assertIn("**1 new listings**", report)

        cheaper = listing(id="a", address="1 Main St", price=1700)
        b = listing(id="b", address="9 Pine St", beds=0, price=1500)
        _, report = run.run(CFG, day2, listings=[cheaper, b], status={"test": "ok"})
        self.assertIn("**1 new listings**", report)
        self.assertIn("9 Pine St", report)
        self.assertIn("Price drops (1)", report)
        self.assertIn("was $1,800", report)


if __name__ == "__main__":
    unittest.main()
