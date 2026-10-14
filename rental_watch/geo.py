"""Location helpers: Caltrain stations and the commute filter."""
import math

# Approximate station coordinates (lat, lon), north to south. Accurate to a
# few hundred feet, which is plenty for a "walk to the train" radius.
CALTRAIN_STATIONS = {
    "San Francisco (4th & King)": (37.7766, -122.3947),
    "22nd Street": (37.7575, -122.3926),
    "Bayshore": (37.7092, -122.4013),
    "South San Francisco": (37.6557, -122.4050),
    "San Bruno": (37.6301, -122.4115),
    "Millbrae": (37.6000, -122.3867),
    "Broadway": (37.5874, -122.3625),
    "Burlingame": (37.5795, -122.3450),
    "San Mateo": (37.5680, -122.3240),
    "Hayward Park": (37.5526, -122.3090),
    "Hillsdale": (37.5373, -122.2973),
    "Belmont": (37.5209, -122.2759),
    "San Carlos": (37.5075, -122.2602),
    "Redwood City": (37.4855, -122.2319),
    "Menlo Park": (37.4545, -122.1823),
    "Palo Alto": (37.4434, -122.1649),
    "California Avenue": (37.4291, -122.1424),
    "San Antonio": (37.4072, -122.1072),
    "Mountain View": (37.3943, -122.0763),
    "Sunnyvale": (37.3784, -122.0308),
    "Lawrence": (37.3705, -121.9973),
    "Santa Clara": (37.3532, -121.9365),
    "College Park": (37.3424, -121.9146),
    "San Jose Diridon": (37.3297, -121.9025),
    "Tamien": (37.3112, -121.8830),
}

REDWOOD_CITY = CALTRAIN_STATIONS["Redwood City"]


def miles_between(a, b):
    """Great-circle distance in miles between two (lat, lon) points."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def nearest_station(point):
    """Return (station_name, miles) for the closest Caltrain station."""
    return min(((name, miles_between(point, coords))
                for name, coords in CALTRAIN_STATIONS.items()),
               key=lambda pair: pair[1])


def commute_check(listing, cfg):
    """Decide whether a listing's location fits the commute rules.

    Returns (ok, note). A listing passes if it is within walking distance of
    any Caltrain station OR within driving range of Redwood City. Listings
    without coordinates fall back to matching their city name.
    """
    if listing.lat is not None and listing.lon is not None:
        point = (listing.lat, listing.lon)
        station, station_mi = nearest_station(point)
        rwc_mi = miles_between(point, REDWOOD_CITY)
        note = f"{station_mi:.1f} mi to {station} Caltrain · {rwc_mi:.1f} mi to Redwood City"
        ok = (station_mi <= cfg["max_miles_to_caltrain"]
              or rwc_mi <= cfg["max_miles_to_redwood_city"])
        return ok, note

    city = (listing.city or "").strip().lower()
    allowed = {c.lower() for c in cfg["cities"]}
    if city in allowed:
        return True, f"{listing.city} (no map pin, so distance not checked)"
    return False, "location unknown"
