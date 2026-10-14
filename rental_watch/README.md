# Rental Watch

Daily scan of rental sites for SF / Peninsula listings that fit your criteria.
Each run reports only listings it hasn't seen before, plus price drops.

**Sources:** Craigslist (SF, Peninsula, South Bay), Zillow, Apartments.com,
Zumper, HotPads, and saved-search alert emails dropped into `inbox/` as `.eml` files.

**Default criteria** (edit `config.toml`): studio or 1 bd, at least 1 bath, $2,000/mo or less,
and either within 1 mile of a Caltrain station or within about 12 miles of Redwood City
(roughly a 30-minute drive). Listings with no map pin are kept if their city is on the list.

```
pip install -r requirements.txt
python run.py          # new listings since last run -> reports/YYYY-MM-DD.md
python run.py --all    # every current match
python -m unittest test_watch
```

State lives in `state/seen.json` (listings are forgotten after 60 days unseen).

Note: Zillow, Apartments.com and HotPads actively block automated access, and their
terms of service prohibit scraping. Those sources may fail on some days; the report's
"Sources" section shows which ones worked. Keep it to personal use at a low request rate.
