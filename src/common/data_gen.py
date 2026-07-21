from random import random

import propagator

def orbit_catalog(cat, time):

    tle = propagator.tle_request(cat)
    orb_data = propagator.propagate(tle, time)
    return orb_data

# random housekeeping data generation for a satellite using "sunlit" status from json to determine temperature ranges
# in celsius, battery level and fuel level are generated randomly between 0-100% and 0-80% respectively
def housekeeping_random(satellite):

    name = satellite["name"]
    battery_level = round(random.uniform(0, 100), 2)
    bus_temp, payload_temp = 0, 0
    if satellite["sunlit"] == True:
        bus_temp = round(random.uniform(100, 150), 2)
        payload_temp = round(random.uniform(100, 150), 2)
    else:
        bus_temp = round(random.uniform(-150, -100), 2)
        payload_temp = round(random.uniform(-150, -100), 2)
    fuel_level = round(random.uniform(0, 80), 2)

    return name, battery_level, bus_temp, payload_temp, fuel_level