import propagator
from sgp4.api import Satrec, WGS84

def orbit_catalog(cat, time):

    tle = propagator.tle_request(cat)
    orb_data = propagator.propagate(tle, time)
    return orb_data

def createOrbit(cat, epoch, bstar, ndot, nddot, ecco, argp, inclo, mo, no_kozai, nodeo):

    satellite = Satrec()
    satellite.sgp4init(
        
        WGS84,  # WGS84 gravity model
        'i', # improved mode
        cat, # satellite catalog number
        epoch, # epoch: days since 1949 December 31 00:00 UT
        bstar, # bstar: drag coeffiecient (/earth radii)
        ndot, # ndot: ballistic coeficient (radians/minute^2)
        nddot, # nddot: second derivative of mean motion (radians/minute^3)
        ecco, # ecco: eccentricity
        argp, # argp: argument of perigee (radians)
        inclo, # inclo: inclination (radians)
        mo, # mo: mean anomaly (radians)
        no_kozai, # no_kozai: mean motion (radians/minute)
        nodeo, # nodeo: right ascension of ascending node (radians)

    )

    return satellite