"""Daily rental watch: scrape every enabled source, keep listings that fit
the criteria, and write a report of the ones not seen before.

    python run.py              # normal daily run
    python run.py --all        # report every match, not just new ones
"""
import argparse
import datetime as dt
import json
import re
import sys
import tomllib
import traceback
from pathlib import Path

from geo import commute_check
from sources import SOURCES, Fetcher

HERE = Path(__file__).parent
STATE = HERE / "state" / "seen.json"
REPORTS = HERE / "reports"
FORGET_AFTER_DAYS = 60


def fits_criteria(l, c):
    if l.price is None or not 300 <= l.price <= c["max_rent"]:   # <300 is usually a parking spot or typo
        return False
    if l.beds is not None and not c["min_beds"] <= l.beds <= c["max_beds"]:
        return False
    if l.baths is not None and l.baths < c["min_baths"]:
        return False
    return True


def same_place_key(l):
    """Catch the same unit posted on several sites."""
    street = re.sub(r"[^a-z0-9]", "", (l.address or l.title).lower())[:30]
    return f"{street}|{l.price}|{l.beds}"


def load_state():
    try:
        return json.loads(STATE.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def save_state(seen, today):
    cutoff = (today - dt.timedelta(days=FORGET_AFTER_DAYS)).isoformat()
    seen = {k: v for k, v in seen.items() if v["last_seen"] >= cutoff}
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(seen, indent=1, sort_keys=True))


def collect(cfg):
    fetch = Fetcher(cfg)
    listings, status = [], {}
    for name, enabled in cfg["sources"].items():
        if not enabled:
            continue
        try:
            got = SOURCES[name](fetch, cfg)
            listings += got
            status[name] = f"ok, {len(got)} listings"
        except Exception as e:
            status[name] = f"FAILED: {type(e).__name__}: {str(e)[:150]}"
            traceback.print_exc(file=sys.stderr)
    return listings, status


def run(cfg, today, report_all=False, listings=None, status=None):
    if listings is None:
        listings, status = collect(cfg)
    seen = load_state()
    matches, places = [], set()
    for l in listings:
        if not fits_criteria(l, cfg["criteria"]):
            continue
        ok, note = commute_check(l, cfg["location"])
        if not ok:
            continue
        place = same_place_key(l)
        if place in places:
            continue
        places.add(place)
        l.extra["commute"] = note
        matches.append(l)

    new, drops = [], []
    for l in matches:
        prev = seen.get(l.key)
        if prev is None:
            new.append(l)
        elif prev.get("price") and l.price < prev["price"]:
            l.extra["was"] = prev["price"]
            drops.append(l)
        seen[l.key] = {"first_seen": (prev or {}).get("first_seen", today.isoformat()),
                       "last_seen": today.isoformat(), "price": l.price, "url": l.url}
    save_state(seen, today)

    shown = matches if report_all else new
    report = render(today, shown, drops, status, len(matches), report_all)
    REPORTS.mkdir(exist_ok=True)
    path = REPORTS / f"{today.isoformat()}.md"
    path.write_text(report)
    return path, report


def describe(l):
    beds = "?" if l.beds is None else ("Studio" if l.beds == 0 else f"{l.beds:g} bd")
    baths = "" if l.baths is None else f" / {l.baths:g} ba"
    where = l.address or l.city
    return (f"- **${l.price:,}** · {beds}{baths} · [{l.title[:70]}]({l.url})\n"
            f"  {where} · {l.extra.get('commute', '')} · _{l.source}_")


def render(today, shown, drops, status, total, report_all):
    lines = [f"# Rentals for {today:%A, %B %-d, %Y}", ""]
    label = "matching listings" if report_all else "new listings"
    lines.append(f"**{len(shown)} {label}** ({total} currently match your criteria in total)")
    lines.append("")
    for l in sorted(shown, key=lambda l: l.price):
        lines.append(describe(l))
    if drops:
        lines += ["", f"## Price drops ({len(drops)})", ""]
        for l in sorted(drops, key=lambda l: l.price):
            lines.append(describe(l) + f" · was ${l.extra['was']:,}")
    lines += ["", "## Sources", ""]
    lines += [f"- {name}: {msg}" for name, msg in status.items()]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="list every match, not only new ones")
    ap.add_argument("--config", default=HERE / "config.toml")
    args = ap.parse_args()
    cfg = tomllib.loads(Path(args.config).read_text())
    path, report = run(cfg, dt.date.today(), report_all=args.all)
    print(report)
    print(f"(saved to {path})")


if __name__ == "__main__":
    main()
