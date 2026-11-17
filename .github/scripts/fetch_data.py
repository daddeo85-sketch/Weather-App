"""Fetch the latest NOAA buoy readings and the NOAA tide station list.

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


def tides(out):
    """NOAA tide prediction stations, refreshed once a week."""
    path = os.path.join(out, "tides.json")
    prev = load(path)
    if prev and prev.get("updated"):
        age = NOW - datetime.datetime.strptime(prev["updated"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
        if age < datetime.timedelta(days=7):
            print("tides: still fresh")
            return
    d = json.loads(get("https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json?type=tidepredictions"))
    rows = [[s["id"], s["name"], round(float(s["lat"]), 4), round(float(s["lng"]), 4)]
            for s in d.get("stations", []) if s.get("lat") is not None and s.get("lng") is not None]
    if len(rows) < 1000:
        raise SystemExit("Tide station list looks short; keeping the old file.")
    with open(path, "w") as f:
        json.dump({"updated": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"), "stations": rows}, f, separators=(",", ":"))
    print("tides:", len(rows), "stations")


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "out"
    os.makedirs(out, exist_ok=True)
    errors = []
    for job in (buoys, tides):
        try:
            job(out)
        except BaseException as e:  # keep going so one bad feed doesn't stop the other
            errors.append("%s: %s" % (job.__name__, e))
    for e in errors:
        print("WARNING", e)
