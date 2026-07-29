import numpy as np
from skyfield.api import load, EarthSatellite
from skyfield.toposlib import wgs84


TLE_REQUEST_TIMEOUT_SECONDS = 10


def tle_request(cat):
    try:
        import requests
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "TLE retrieval requires the optional runtime dependency "
            "'requests'; install the project dependencies first"
        ) from exc

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"}
    response = requests.get(
        f"https://tle.ivanstanojevic.me/api/tle/{cat}",
        headers=headers,
        timeout=TLE_REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    tle = response.json()
    return tle

def propagate(tle, time):
    
    ts = load.timescale()
    name = tle["name"]
    line_1 = tle["line1"]
    line_2 = tle["line2"]

    date_time = {
    "year": time["year"],
    "month": time["month"],
    "day": time["day"],
    "hour": time["hour"],
    "minute": time["minute"],
    "second": time["second"]
    }

    t = ts.utc(
        date_time["year"],
        date_time["month"],
        date_time["day"],
        date_time["hour"],
        date_time["minute"],
        date_time["second"],
    )
    sat = EarthSatellite(line_1, line_2, name, ts)
    geocentric = sat.at(t)
    s_subpoint = wgs84.subpoint(geocentric)

    r = geocentric.position.km
    v = geocentric.velocity.km_per_s

    r_hat = r / np.linalg.norm(r)
    h_hat = np.cross(r, v) / np.linalg.norm(np.cross(r, v))
    s_hat = np.cross(h_hat, r_hat)

    v_radial = np.dot(v, r_hat)
    v_along = np.dot(v, s_hat)
    v_cross = np.dot(v, h_hat)

    eph = load("de421.bsp")
    try:
        sunlit = geocentric.is_sunlit(eph)
    finally:
        eph.close()

    orbital = {
    "name": name,
    "catalog": sat.model.satnum,
    "coordinate_frame": "ECI",
    "position_km": [float(component) for component in r],
    "cartesian_velocity_km_s": [float(component) for component in v],
    "altitude": s_subpoint.elevation.km,
    "latitude": s_subpoint.latitude.degrees,
    "longitude": s_subpoint.longitude.degrees,
    "velocity_km_s": {
        "radial": v_radial,
        "along": v_along,
        "cross": v_cross
    },
    "speed_km_s": np.linalg.norm(v),
    "sunlit": bool(sunlit),
    "time": date_time
    }

    return orbital
