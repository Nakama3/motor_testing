"""Listing sources. Each source yields Listing objects and never raises:
failures are recorded so the daily report can say which sites broke."""
import email
import email.policy
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

try:
    from curl_cffi import requests as http   # browser-like TLS fingerprint
    _IMPERSONATE = {"impersonate": "chrome"}
except ImportError:                            # plain requests still works for some sites
    import requests as http
    _IMPERSONATE = {}

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass
class Listing:
    source: str
    id: str
    url: str
    title: str
    price: int | None = None
    beds: float | None = None
    baths: float | None = None
    address: str = ""
    city: str = ""
    lat: float | None = None
    lon: float | None = None
    extra: dict = field(default_factory=dict)

    @property
    def key(self):
        return f"{self.source}:{self.id}"


class Fetcher:
    def __init__(self, cfg):
        self.delay = cfg["fetch"]["delay_seconds"]
        self.timeout = cfg["fetch"]["timeout_seconds"]
        self.session = http.Session()
        self._last = {}

    def _wait(self, url):
        host = url.split("/")[2]
        gap = time.time() - self._last.get(host, 0)
        if gap < self.delay:
            time.sleep(self.delay - gap)
        self._last[host] = time.time()

    def get(self, url, **kw):
        self._wait(url)
        r = self.session.get(url, headers=HEADERS, timeout=self.timeout, **_IMPERSONATE, **kw)
        r.raise_for_status()
        return r.text

    def put_json(self, url, body):
        self._wait(url)
        r = self.session.put(url, json=body, timeout=self.timeout,
                             headers={**HEADERS, "Content-Type": "application/json"},
                             **_IMPERSONATE)
        r.raise_for_status()
        return r.json()


# ---------------------------------------------------------------- helpers

def parse_price(text):
    """'$1,950/mo' -> 1950; '$1,800+' -> 1800; ranges take the low end."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return int(text)
    m = re.search(r"\$?\s*(\d[\d,]*)", str(text))
    return int(m.group(1).replace(",", "")) if m else None


def parse_beds(text):
    """'Studio' -> 0, '1 bd' / '1 Bed' / '1br' -> 1."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    t = str(text).lower()
    if "studio" in t:
        return 0.0
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:bd|bed|br|bedroom)", t) or re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*", t)
    return float(m.group(1)) if m else None


def parse_baths(text):
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:ba|bath)", str(text).lower()) or re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*", str(text))
    return float(m.group(1)) if m else None


def to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def city_slug(city):
    return re.sub(r"[^a-z0-9]+", "-", city.lower()).strip("-") + "-ca"


def embedded_json(html):
    """Yield every JSON blob a page embeds (JSON-LD, Next.js data, etc.)."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all("script"):
        kind = (tag.get("type") or "").lower()
        text = tag.string or tag.get_text() or ""
        if kind in ("application/ld+json", "application/json"):
            try:
                yield json.loads(text)
            except ValueError:
                pass
            continue
        # window.__SOMETHING__ = {...};
        m = re.search(r"=\s*(\{.*\})\s*;?\s*$", text.strip(), re.S)
        if m and "__" in text[:200]:
            try:
                yield json.loads(m.group(1))
            except ValueError:
                pass


def walk(obj):
    """Depth-first walk over every dict inside a JSON structure."""
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            yield cur
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)


def _first(d, *keys):
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, ""):
            return d[k]
    return None


def generic_listings(html, source, base_url, default_city=""):
    """Best-effort extraction of listing-shaped objects from embedded JSON.

    Used for sites whose markup changes often. An object counts as a listing
    if it has a URL and either a price or an address."""
    found = {}
    for blob in embedded_json(html):
        for d in walk(blob):
            url = _first(d, "url", "detailUrl", "listingUrl", "pdpUrl", "link")
            if not isinstance(url, str) or len(url) < 8:
                continue
            offers = d.get("offers") if isinstance(d.get("offers"), dict) else {}
            price = parse_price(_first(d, "price", "minPrice", "rent", "min_price", "priceMin")
                                or _first(offers, "price", "lowPrice"))
            addr = d.get("address")
            if isinstance(addr, dict):
                city = addr.get("addressLocality") or addr.get("city") or default_city
                addr = " ".join(str(addr.get(k, "")) for k in ("streetAddress", "addressLocality")).strip()
            else:
                city = _first(d, "city", "addressCity") or default_city
                addr = addr if isinstance(addr, str) else ""
            if price is None and not addr:
                continue
            geo = d.get("geo") if isinstance(d.get("geo"), dict) else d
            lat = _first(geo, "latitude", "lat")
            lon = _first(geo, "longitude", "lng", "lon")
            full_url = urljoin(base_url, url)
            lid = _first(d, "listingId", "listing_id", "id", "@id") or full_url
            found[full_url] = Listing(
                source=source, id=str(lid), url=full_url,
                title=str(_first(d, "name", "title", "buildingName") or addr or "Listing"),
                price=price,
                beds=parse_beds(_first(d, "numberOfBedrooms", "beds", "bedrooms", "min_bedrooms")),
                baths=parse_baths(_first(d, "numberOfBathroomsTotal", "baths", "bathrooms", "min_bathrooms")),
                address=addr, city=str(city or ""),
                lat=to_float(lat), lon=to_float(lon),
            )
    return list(found.values())


# ---------------------------------------------------------------- sources

def craigslist(fetch, cfg):
    c = cfg["criteria"]
    out = []
    for area in cfg["craigslist"]["subareas"]:
        url = (f"https://sfbay.craigslist.org/search/{area}/apa?max_price={c['max_rent']}"
               f"&min_bedrooms={c['min_beds']}&max_bedrooms={c['max_beds']}"
               f"&min_bathrooms={c['min_baths']}&availabilityMode=0")
        out += parse_craigslist(fetch.get(url))
    return out


def parse_craigslist(html):
    soup = BeautifulSoup(html, "lxml")
    # Structured data (beds, map pins) sits in a JSON-LD block, in the same
    # order as the plain HTML result list that carries the links.
    ld = []
    tag = soup.find("script", id="ld_searchpage_results")
    if tag and tag.string:
        try:
            ld = [e.get("item", {}) for e in json.loads(tag.string).get("itemListElement", [])]
        except ValueError:
            ld = []
    out = []
    for i, li in enumerate(soup.select("li.cl-static-search-result")):
        a = li.find("a", href=True)
        if not a:
            continue
        m = re.search(r"/(\d+)\.html", a["href"])
        item = ld[i] if i < len(ld) else {}
        addr = item.get("address", {}) if isinstance(item.get("address"), dict) else {}
        loc = li.select_one(".location")
        price = li.select_one(".price")
        out.append(Listing(
            source="craigslist", id=m.group(1) if m else a["href"], url=a["href"],
            title=li.get("title") or a.get_text(" ", strip=True),
            price=parse_price(price.get_text() if price else None),
            beds=parse_beds(item.get("numberOfBedrooms")),
            baths=parse_baths(item.get("numberOfBathroomsTotal")),
            address=(loc.get_text(strip=True) if loc else ""),
            city=addr.get("addressLocality", "") or (loc.get_text(strip=True) if loc else ""),
            lat=to_float(item.get("latitude")), lon=to_float(item.get("longitude")),
        ))
    return out


def zillow(fetch, cfg):
    c = cfg["criteria"]
    out = []
    for west, east, south, north in cfg["zillow"]["boxes"]:
        for page in range(1, cfg["zillow"]["max_pages"] + 1):
            state = {
                "pagination": {"currentPage": page},
                "isMapVisible": True, "isListVisible": True,
                "mapBounds": {"west": west, "east": east, "south": south, "north": north},
                "filterState": {
                    "fr": {"value": True}, "fsba": {"value": False}, "fsbo": {"value": False},
                    "nc": {"value": False}, "cmsn": {"value": False}, "auc": {"value": False},
                    "fore": {"value": False},
                    "mp": {"max": c["max_rent"]},
                    "beds": {"min": c["min_beds"], "max": c["max_beds"]},
                    "baths": {"min": c["min_baths"]},
                },
            }
            try:
                data = fetch.put_json("https://www.zillow.com/async-create-search-page-state",
                                      {"searchQueryState": state, "wants": {"cat1": ["listResults"]},
                                       "requestId": page})
                results = data["cat1"]["searchResults"]["listResults"]
            except Exception:
                # Fall back to the regular page, which embeds the same data.
                html = fetch.get("https://www.zillow.com/rentals/?searchQueryState="
                                 + quote(json.dumps(state, separators=(",", ":"))))
                results = parse_zillow_page(html)
            batch = [l for r in results for l in zillow_result(r)]
            out += batch
            if len(results) < 40:   # last page
                break
    return out


def parse_zillow_page(html):
    for blob in embedded_json(html):
        for d in walk(blob):
            if isinstance(d.get("listResults"), list):
                return d["listResults"]
    raise ValueError("no listResults in Zillow page (likely blocked by a captcha)")


def zillow_result(r):
    """One Zillow search result. Apartment buildings list several units."""
    latlong = r.get("latLong") or {}
    base = dict(source="zillow", address=r.get("address", ""),
                city=r.get("addressCity", ""),
                lat=to_float(latlong.get("latitude")), lon=to_float(latlong.get("longitude")))
    url = urljoin("https://www.zillow.com", r.get("detailUrl", ""))
    rid = str(r.get("zpid") or r.get("lotId") or r.get("id") or url)
    units = r.get("units") or []
    if units:
        return [Listing(id=f"{rid}-{i}", url=url,
                        title=r.get("buildingName") or r.get("statusText") or "Apartment building",
                        price=parse_price(u.get("price")), beds=parse_beds(u.get("beds")),
                        baths=None, **base)
                for i, u in enumerate(units)]
    return [Listing(id=rid, url=url, title=r.get("statusText") or r.get("address", "Rental"),
                    price=parse_price(r.get("unformattedPrice") or r.get("price")),
                    beds=parse_beds(r.get("beds")), baths=parse_baths(r.get("baths")), **base)]


def apartments_com(fetch, cfg):
    c = cfg["criteria"]
    out = []
    beds = "studios-1-bedrooms" if c["min_beds"] == 0 else "1-bedrooms"
    for city in cfg["location"]["cities"]:
        url = f"https://www.apartments.com/{city_slug(city)}/{beds}-under-{c['max_rent']}/"
        out += parse_apartments_com(fetch.get(url), city)
    return out


def parse_apartments_com(html, city):
    soup = BeautifulSoup(html, "lxml")
    out = []
    for art in soup.select("article.placard, li.mortar-wrapper article"):
        url = art.get("data-url") or (art.find("a", href=True) or {}).get("href")
        if not url:
            continue
        text = lambda sel: (art.select_one(sel).get_text(" ", strip=True) if art.select_one(sel) else "")
        out.append(Listing(
            source="apartments.com", id=art.get("data-listingid") or url, url=url,
            title=text(".property-title, .js-placardTitle") or "Apartment",
            price=parse_price(text(".property-pricing, .price-range, .property-rents")),
            beds=parse_beds(text(".property-beds, .bed-range")),
            address=text(".property-address"), city=city,
        ))
    return out or generic_listings(html, "apartments.com", "https://www.apartments.com", city)


def zumper(fetch, cfg):
    c = cfg["criteria"]
    out = []
    for city in cfg["location"]["cities"]:
        url = (f"https://www.zumper.com/apartments-for-rent/{city_slug(city)}"
               f"?bedrooms={c['min_beds']},{c['max_beds']}&price-max={c['max_rent']}")
        out += generic_listings(fetch.get(url), "zumper", "https://www.zumper.com", city)
    return out


def hotpads(fetch, cfg):
    c = cfg["criteria"]
    out = []
    beds = ",".join(str(b) for b in range(c["min_beds"], c["max_beds"] + 1))
    for city in cfg["location"]["cities"]:
        url = (f"https://hotpads.com/{city_slug(city)}/apartments-for-rent"
               f"?beds={beds}&price=0-{c['max_rent']}")
        out += generic_listings(fetch.get(url), "hotpads", "https://hotpads.com", city)
    return out


def email_alerts(fetch, cfg, inbox=Path(__file__).parent / "inbox"):
    """Listings from saved-search alert emails (Zillow, Apartments.com, ...)
    saved as .eml files in the inbox folder. Processed files are moved to
    inbox/done/."""
    out = []
    done = inbox / "done"
    for path in sorted(inbox.glob("*.eml")):
        msg = email.message_from_bytes(path.read_bytes(), policy=email.policy.default)
        body = msg.get_body(preferencelist=("html", "plain"))
        out += parse_alert_email(body.get_content() if body else "")
        done.mkdir(exist_ok=True)
        path.rename(done / path.name)
    return out


LISTING_LINK = re.compile(
    r"(zillow\.com/(homedetails|apartments|b)/|apartments\.com/[^\"' ]+/[a-z0-9]{6,}/|"
    r"hotpads\.com/[^\"' ]+/pad|zumper\.com/apartment-buildings/|craigslist\.org/.+/\d+\.html)")


def parse_alert_email(html):
    soup = BeautifulSoup(html, "lxml")
    out = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].split("?")[0]
        if not LISTING_LINK.search(href) or href in out:
            continue
        # The listing's details usually live in the enclosing table cell.
        block = a
        for _ in range(4):
            if block.parent is not None and len(block.parent.get_text(" ", strip=True)) < 400:
                block = block.parent
        text = block.get_text(" ", strip=True)
        site = re.search(r"(zillow|apartments|hotpads|zumper|craigslist)", href).group(1)
        out[href] = Listing(
            source=f"{site} (email)", id=href, url=href,
            title=a.get_text(" ", strip=True) or text[:80],
            price=parse_price(re.search(r"\$[\d,]+", text).group(0)) if "$" in text else None,
            beds=parse_beds(text), baths=parse_baths(text), address=text[:120],
        )
    return list(out.values())


SOURCES = {
    "craigslist": craigslist,
    "zillow": zillow,
    "apartments_com": apartments_com,
    "zumper": zumper,
    "hotpads": hotpads,
    "email_alerts": email_alerts,
}
