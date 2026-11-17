"""Fetch the latest NOAA buoy readings, NOAA station lists and a US airport list.

The web page can't read NOAA's buoy files directly (the browser blocks them),
so this runs on a schedule in GitHub Actions and saves small JSON files to the
"data" branch, which the page reads.
"""
import datetime
import json
import os
import sys
import urllib.request

UA = {"User-Agent": "weather-app-data/1.0"}
NOW = datetime.datetime.now(datetime.timezone.utc)


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read().decode("utf-8", "replace")


def num(x):
    try:
        return None if x == "MM" else float(x)
    except ValueError:
        return None


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def buoys(out):
    """Wave buoys from NDBC's latest_obs.txt, merged with the last run so an
    offline buoy keeps its last reading (the page shows N/A once it's old)."""
    path = os.path.join(out, "buoys.json")
    prev = load(path) or {}
    keep = {b["id"]: b for b in prev.get("buoys", [])}
    txt = get("https://www.ndbc.noaa.gov/data/latest_obs/latest_obs.txt")
    fresh = 0
    for line in txt.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        c = line.split()
        if len(c) < 22:
            continue
        wv = num(c[11])
        if wv is None:
            continue
        try:
            t = datetime.datetime(int(c[3]), int(c[4]), int(c[5]), int(c[6]), int(c[7]), tzinfo=datetime.timezone.utc)
        except ValueError:
            continue
        wt = num(c[18])
        keep[c[0]] = {
            "id": c[0], "lat": float(c[1]), "lon": float(c[2]),
            "t": t.strftime("%Y-%m-%dT%H:%M:00Z"),
            "ft": round(wv * 3.28084, 1),
            "dpd": num(c[12]), "apd": num(c[13]), "mwd": num(c[14]),
            "wtf": round(wt * 9 / 5 + 32) if wt is not None else None,
        }
        fresh += 1
    if fresh == 0:
        raise SystemExit("No buoy rows parsed; keeping the old file.")
    cutoff = NOW - datetime.timedelta(days=30)
    rows = [b for b in keep.values()
            if datetime.datetime.strptime(b["t"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc) > cutoff]
    rows.sort(key=lambda b: b["id"])
    with open(path, "w") as f:
        json.dump({"updated": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"), "buoys": rows}, f, separators=(",", ":"))
    print("buoys:", fresh, "reporting,", len(rows), "kept")


def fresh(path, days):
    prev = load(path)
    if prev and prev.get("updated"):
        age = NOW - datetime.datetime.strptime(prev["updated"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
        return age < datetime.timedelta(days=days)
    return False


def stations(kind):
    d = json.loads(get("https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json?type=" + kind))
    return [[s["id"], s["name"], round(float(s["lat"]), 4), round(float(s["lng"]), 4)]
            for s in d.get("stations", []) if s.get("lat") is not None and s.get("lng") is not None]


def tides(out):
    """NOAA tide prediction stations and water temperature stations, refreshed once a week."""
    path = os.path.join(out, "tides.json")
    prev = load(path) or {}
    if fresh(path, 7) and prev.get("wt"):
        print("tides: still fresh")
        return
    rows = stations("tidepredictions")
    if len(rows) < 1000:
        raise SystemExit("Tide station list looks short; keeping the old file.")
    try:
        wt = stations("watertemp")
    except Exception as e:
        print("WARNING water temp stations:", e)
        wt = prev.get("wt", [])
    with open(path, "w") as f:
        json.dump({"updated": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"), "stations": rows, "wt": wt}, f, separators=(",", ":"))
    print("tides:", len(rows), "stations,", len(wt), "water temp stations")


def airports(out):
    """US airports from OurAirports (public domain), refreshed once a week. Big and
    mid-size airports, plus small ones with a K code (public-use fields)."""
    import csv
    import io
    import re
    path = os.path.join(out, "airports.json")
    if fresh(path, 7) and os.path.isdir(os.path.join(out, "ap")):
        print("airports: still fresh")
        return
    txt = get("https://davidmegginson.github.io/ourairports-data/airports.csv")
    rows, tiles = [], {}
    kinds = {"large_airport": "L", "medium_airport": "M", "small_airport": "S", "heliport": "H", "seaplane_base": "W"}
    for r in csv.DictReader(io.StringIO(txt)):
        k = kinds.get(r.get("type"))
        if not k or r.get("iso_country") not in ("US", "PR", "VI", "GU"):
            continue
        code = (r.get("icao_code") or r.get("gps_code") or r.get("ident") or "").strip()
        try:
            lat, lon = round(float(r["latitude_deg"]), 4), round(float(r["longitude_deg"]), 4)
        except (TypeError, ValueError):
            continue
        row = [code, r.get("name", ""), lat, lon, k, (r.get("iata_code") or "").strip(),
               (r.get("municipality") or "").strip(), (r.get("iso_region") or "").replace("US-", "")]
        # every field, private strip and heliport goes into 2-degree tiles for "Airports near you"
        tiles.setdefault("%d_%d" % (int(lat // 2) * 2, int(lon // 2) * 2), []).append(row)
        if k in "HW" or (k == "S" and not re.match(r"^K[A-Z0-9]{3}$", code)):
            continue
        rows.append(row)
    if len(rows) < 1000:
        raise SystemExit("Airport list looks short; keeping the old file.")
    os.makedirs(os.path.join(out, "ap"), exist_ok=True)
    for key, t in tiles.items():
        with open(os.path.join(out, "ap", key + ".json"), "w") as f:
            json.dump(t, f, separators=(",", ":"))
    print("airport tiles:", len(tiles))
    with open(path, "w") as f:
        json.dump({"updated": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"), "airports": rows}, f, separators=(",", ":"))
    print("airports:", len(rows))


def launches(out):
    """Upcoming rocket launches from The Space Devs Launch Library 2 (free tier,
    about 15 calls an hour), refreshed at most every 25 minutes."""
    path = os.path.join(out, "launches.json")
    prev = load(path)
    if prev and prev.get("updated"):
        age = NOW - datetime.datetime.strptime(prev["updated"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
        if age < datetime.timedelta(minutes=25):
            print("launches: still fresh")
            return
    d = json.loads(get("https://ll.thespacedevs.com/2.3.0/launches/upcoming/?limit=60&mode=normal"))
    rows = []
    for l in d.get("results", []):
        pad = l.get("pad") or {}
        loc = pad.get("location") or {}
        st = l.get("status") or {}
        lsp = l.get("launch_service_provider") or {}
        rk = ((l.get("rocket") or {}).get("configuration") or {})
        ms = l.get("mission") or {}
        img = l.get("image")
        if isinstance(img, dict):
            img = img.get("thumbnail_url") or img.get("image_url")
        try:
            plat, plon = float(pad.get("latitude")), float(pad.get("longitude"))
        except (TypeError, ValueError):
            plat = plon = None
        rows.append({"name": l.get("name"), "net": l.get("net"), "ws": l.get("window_start"), "we": l.get("window_end"),
                     "st": st.get("abbrev"), "stn": st.get("name"), "prov": lsp.get("name"),
                     "rocket": rk.get("full_name") or rk.get("name"), "pad": pad.get("name"), "loc": loc.get("name"),
                     "lat": plat, "lon": plon, "mission": ms.get("name"), "desc": (ms.get("description") or "")[:400],
                     "orbit": (ms.get("orbit") or {}).get("name"), "img": img})
    if not rows:
        raise SystemExit("No launches came back; keeping the old file.")
    with open(path, "w") as f:
        json.dump({"updated": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"), "launches": rows}, f, separators=(",", ":"))
    print("launches:", len(rows))


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "out"
    os.makedirs(out, exist_ok=True)
    errors = []
    for job in (buoys, tides, airports, launches):
        try:
            job(out)
        except BaseException as e:  # keep going so one bad feed doesn't stop the other
            errors.append("%s: %s" % (job.__name__, e))
    for e in errors:
        print("WARNING", e)
