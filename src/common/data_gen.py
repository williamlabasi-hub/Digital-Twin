import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import preprocessing.tle_propagator as tle_propagator
from sgp4.api import Satrec, WGS84
import numpy as np
from scipy.optimize import minimize

def orbit_catalog(cat, time):

    tle = tle_propagator.tle_request(cat)
    orb_data = tle_propagator.propagate(tle, time)
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

def closeApproach():

    # ADD AUTO e, a, AND i BASED ON A DESIRED DISTANCE
    # ADD ALLOW OPERATOR TO PICK CANDIDATE SUGGESTION TO RERUN FOR HIGHER FIDELITY RESULTS
    # FACTOR CODE TO WORK WITHIN THE SYSTEM AS A WHOLE (E.G. ADDING A FUNCTION TO CALL THIS FUNCTION WITH
    # A DESIRED DISTANCE AND RETURN RESULTS TO THE USER)
    
    MU_EARTH = 398600.4418  # km^3/s^2

    def elems_to_position(elems, nu):
        # Vectorized position(s) on a Keplerian ellipse in ECI

        # elems: (a, e, i, raan, argp)  -- km, dimensionless, radians
        # nu:    scalar or ndarray of true anomalies (radians)

        # Returns array of shape (3,) or (3, N) matching nu's shape

        a, e, i, raan, argp = elems
        nu = np.asarray(nu, dtype=float)

        r = a * (1 - e**2) / (1 + e * np.cos(nu))
        # perifocal coordinates
        x_pf = r * np.cos(nu)
        y_pf = r * np.sin(nu)
        z_pf = np.zeros_like(nu)

        cO, sO = np.cos(raan), np.sin(raan)
        ci, si = np.cos(i), np.sin(i)
        cw, sw = np.cos(argp), np.sin(argp)

        # Combined perifocal -> ECI rotation matrix (3-1-3: Rz(raan) Rx(i) Rz(argp))
        R = np.array([
            [cO*cw - sO*sw*ci,  -cO*sw - sO*cw*ci,   sO*si],
            [sO*cw + cO*sw*ci,  -sO*sw + cO*cw*ci,  -cO*si],
            [sw*si,              cw*si,               ci  ],
        ])
        pf = np.stack([x_pf, y_pf, z_pf], axis=0)  # (3, N) or (3,)

        return R @ pf

    def moid(elems1, elems2, grid_n=180, verbose=False):
        
        # Geometric MOID between two closed Keplerian orbits (km)

        # vectorized coarse grid over (nu1, nu2) in [0, 2pi)^2 to bracket
        # local minima of the distance surface, then Nelder-Mead refinement of each
        # bracket (robust to the non-smooth min() at wraparound and avoids needing
        # analytic gradients)
        

        nu = np.linspace(0, 2 * np.pi, grid_n, endpoint=False)

        P1 = elems_to_position(elems1, nu)  # (3, N)
        P2 = elems_to_position(elems2, nu)  # (3, N)

        # Pairwise distance matrix D[i, j] = |P1[:,i] - P2[:,j]|
        diff = P1[:, :, None] - P2[:, None, :]      # (3, N, N)
        D = np.sqrt(np.einsum('kij,kij->ij', diff, diff))

        # Find local minima on the toroidal grid (vectorized 4-neighbor compare,
        # wrapping via np.roll -- avoids an O(grid_n^2) Python-level loop)
        is_min = (
            (D <= np.roll(D, 1, axis=0)) & (D <= np.roll(D, -1, axis=0)) &
            (D <= np.roll(D, 1, axis=1)) & (D <= np.roll(D, -1, axis=1))
        )
        idx_i, idx_j = np.nonzero(is_min)
        candidates = [(nu[i], nu[j], D[i, j]) for i, j in zip(idx_i, idx_j)]

        if not candidates:
            # fallback: just take the global grid minimum
            i, j = np.unravel_index(np.argmin(D), D.shape)
            candidates = [(nu[i], nu[j], D[i, j])]

        def dist_fn(x):
            p1 = elems_to_position(elems1, x[0])
            p2 = elems_to_position(elems2, x[1])
            return np.linalg.norm(p1 - p2)

        refined = []
        for nu1_0, nu2_0, _ in candidates:
            res = minimize(dist_fn, x0=[nu1_0, nu2_0], method='Nelder-Mead',
                           options={'xatol': 1e-10, 'fatol': 1e-8})
            refined.append(res.fun)

        best = min(refined)
        if verbose:
            print(f"  {len(candidates)} local minima found, best = {best:.3f} km")
        return best

    def feasible_moid_range(target_elems, a, e, i, grid_n=90, n_scan=8):

        # Coarse estimate of the achievable MOID range against target_elems for
        # fixed (a, e, i), scanning over (raan, argp). Returns (lo, hi) in km

        scan_vals = np.linspace(0, 2 * np.pi, n_scan, endpoint=False)
        scan_moids = [
            moid((a, e, i, r, w), target_elems, grid_n=grid_n)
            for r in scan_vals for w in scan_vals
        ]
        return min(scan_moids), max(scan_moids)

    def design_orbit(target_elems, a, e, i, d_desired, seeds=None, grid_n=120):
        
        # Search for (raan, argp) with a, e, i fixed such that MOID(candidate, target) ~= d_desired

        # Runs from multiple seeds (since the cost surface is multimodal) and
        # returns all distinct converged solutions, sorted by how close they got
        
        if seeds is None:
            # spread seeds across the (raan, argp) torus
            vals = [0, np.pi / 2, np.pi, 3 * np.pi / 2]
            seeds = [(r, w) for r in vals for w in vals]

        feas_lo, feas_hi = feasible_moid_range(target_elems, a, e, i, grid_n=grid_n)
        if not (feas_lo - 0.1 * (feas_hi - feas_lo) <= d_desired <=
                feas_hi + 0.1 * (feas_hi - feas_lo)):
            print(f"  [warning] d_desired={d_desired} km looks outside the "
                  f"roughly achievable range [{feas_lo:.1f}, {feas_hi:.1f}] km "
                  f"for this (a, e, i). Consider adjusting a/e/i instead of "
                  f"just (raan, argp).")

        def cost(p):
            candidate = (a, e, i, p[0], p[1])
            m = moid(candidate, target_elems, grid_n=grid_n)
            return (m - d_desired) ** 2

        results = []
        for p0 in seeds:
            res = minimize(cost, x0=p0, method='Nelder-Mead',
                            options={'xatol': 1e-3, 'fatol': 1e-4, 'maxiter': 200})
            raan, argp = res.x[0] % (2 * np.pi), res.x[1] % (2 * np.pi)
            achieved = moid((a, e, i, raan, argp), target_elems, grid_n=grid_n)
            results.append({
                'raan_deg': np.degrees(raan),
                'argp_deg': np.degrees(argp),
                'achieved_moid_km': achieved,
                'error_km': achieved - d_desired,
            })

        # de-duplicate near-identical solutions (within 0.5 deg in both angles)
        unique = []
        for r in sorted(results, key=lambda r: abs(r['error_km'])):
            if not any(
                abs(r['raan_deg'] - u['raan_deg']) < 0.5 and
                abs(r['argp_deg'] - u['argp_deg']) < 0.5
                for u in unique
            ):
                unique.append(r)

        return unique

    def design_orbit_auto(target_elems, a0, e0, i0, d_desired,
                       a_bounds=None, e_bounds=None, i_bounds=None,
                       weight_a=1.0, weight_e=1.0, weight_i=1.0,
                       n_seeds=8, grid_n=90, force_full_search=False):
        """
        Like design_orbit, but automatically relaxes a, e, and/or i away from
        their nominal values (a0, e0, i0) if -- and only if -- (raan, argp)
        alone can't reach d_desired for the nominal elements.

        This is a 5D search, so it costs more than design_orbit; it's meant to
        be a fallback, not a default. It minimizes a weighted objective:

            (achieved_MOID - d_desired)^2
                + weight_a * ((a - a0) / a_scale)^2
                + weight_e * ((e - e0) / e_scale)^2
                + weight_i * ((i - i0) / i_scale)^2

        so it finds the *smallest* deviation from your nominal mission elements
        that still hits the target distance, rather than wandering arbitrarily
        far through element space. Raise weight_a/e/i to penalize drifting that
        parameter more; lower to let it move more freely.

        Bounds default to a generous but acceptable window around the
        nominal values if not supplied:
          a_bounds: (max(6600, a0-500), a0+500)  km   [6600 km ~ 220 km altitude]
          e_bounds: (0, min(0.9, e0+0.2))
          i_bounds: (max(0, i0-30deg), min(180deg, i0+30deg))

        Returns a dict with the best solution found, plus how much each fixed
        element had to move from nominal (useful to sanity check the result
        against real mission constraints -- this function has no notion of
        which deviations are actually acceptable for your mission).
        """
        a_bounds = a_bounds or (max(6600.0, a0 - 500.0), a0 + 500.0)
        e_bounds = e_bounds or (0.0, min(0.9, e0 + 0.2))
        i_bounds = i_bounds or (max(0.0, i0 - np.radians(30)),
                                 min(np.pi, i0 + np.radians(30)))

        # Only pay for the full 5D search if the cheap 2D search can't do it.
        if not force_full_search:
            feas_lo, feas_hi = feasible_moid_range(target_elems, a0, e0, i0,
                                                    grid_n=grid_n)
            if feas_lo <= d_desired <= feas_hi:
                print(f"  d_desired={d_desired} km is reachable with nominal "
                      f"(a, e, i) alone [{feas_lo:.1f}, {feas_hi:.1f}] km -- "
                      f"running the cheaper (raan, argp)-only search.")
                sols = design_orbit(target_elems, a0, e0, i0, d_desired,
                                     grid_n=grid_n)
                best = sols[0]
                return {
                    'a': a0, 'e': e0, 'i': i0,
                    'raan_deg': best['raan_deg'], 'argp_deg': best['argp_deg'],
                    'achieved_moid_km': best['achieved_moid_km'],
                    'error_km': best['error_km'],
                    'delta_a_km': 0.0, 'delta_e': 0.0, 'delta_i_deg': 0.0,
                }
            print(f"  d_desired={d_desired} km is outside the nominal-element "
                  f"range [{feas_lo:.1f}, {feas_hi:.1f}] km -- "
                  f"searching a, e, i as well.")

        a_scale, e_scale, i_scale = 100.0, 0.01, np.radians(1.0)  # normalization

        def cost(p):
            a, e, i, raan, argp = p
            m = moid((a, e, i, raan, argp), target_elems, grid_n=grid_n)
            return (
                (m - d_desired) ** 2
                + weight_a * ((a - a0) / a_scale) ** 2
                + weight_e * ((e - e0) / e_scale) ** 2
                + weight_i * ((i - i0) / i_scale) ** 2
            )

        bounds = [a_bounds, e_bounds, i_bounds, (0, 2 * np.pi), (0, 2 * np.pi)]

        raan_seeds = np.linspace(0, 2 * np.pi, n_seeds, endpoint=False)
        results = []
        for raan0 in raan_seeds:
            x0 = [a0, e0, i0, raan0, 0.0]
            res = minimize(cost, x0=x0, method='Nelder-Mead', bounds=bounds,
                            options={'xatol': 1e-2, 'fatol': 1e-3, 'maxiter': 150})
            a, e, i, raan, argp = res.x
            raan, argp = raan % (2 * np.pi), argp % (2 * np.pi)
            achieved = moid((a, e, i, raan, argp), target_elems, grid_n=grid_n)
            results.append({
                'a': a, 'e': e, 'i': i,
                'raan_deg': np.degrees(raan), 'argp_deg': np.degrees(argp),
                'achieved_moid_km': achieved,
                'error_km': achieved - d_desired,
                'delta_a_km': a - a0,
                'delta_e': e - e0,
                'delta_i_deg': np.degrees(i - i0),
            })

        best = min(results, key=lambda r: abs(r['error_km']))
        return best

    def tle_to_elements(line1, line2):

        # Search for (raan, argp) -- with a, e, i fixed -- such that MOID(candidate, target) ~= d_desired.
        # Runs from multiple seeds (since the cost surface is multimodal) and
        # returns all distinct converged solutions, sorted by how close they got

        sat = Satrec.twoline2rv(line1, line2)
        e = sat.ecco
        i = sat.inclo                     # rad
        raan = sat.nodeo                  # rad
        argp = sat.argpo                  # rad
        n = sat.no_kozai / 60.0           # rad/s (no_kozai is rad/min)
        a = (MU_EARTH / n**2) ** (1 / 3)  # km, from mean motion via Kepler's third law
        return (a, e, i, raan, argp)

    SAMPLE_TLE = (
    "ISS (ZARYA)",
    "1 25544U 98067A   24001.50000000  .00016717  00000-0  10270-3 0  9000",
    "2 25544  51.6416 339.6058 0007976  35.9128 324.2381 15.50232710000010",
    )

    name, l1, l2 = SAMPLE_TLE
    target = tle_to_elements(l1, l2)
    a_t, e_t, i_t, raan_t, argp_t = target

    print(f"Target orbit ({name}):")
    print(f"  a={a_t:.1f} km, e={e_t:.5f}, i={np.degrees(i_t):.3f} deg, "
          f"raan={np.degrees(raan_t):.3f} deg, argp={np.degrees(argp_t):.3f} deg\n")

    # Design a new orbit: similar altitude/eccentricity, inclination raised by
    # 5 deg, searching (raan, argp) to achieve a MOID of ~50 km.
    a_new = a_t + 20.0        # km, slightly higher altitude
    e_new = e_t
    i_new = i_t + np.radians(5.0)
    d_desired = 50.0          # km (within the reachable range for this a,e,i)

    print(f"Designing orbit: a={a_new:.1f} km, e={e_new:.5f}, "
          f"i={np.degrees(i_new):.3f} deg, target MOID={d_desired} km\n")

    solutions = design_orbit(target, a_new, e_new, i_new, d_desired, grid_n=90)

    print(f"Found {len(solutions)} distinct solution(s):\n")
    for s in solutions:
        print(f"  raan={s['raan_deg']:7.3f} deg  argp={s['argp_deg']:7.3f} deg  "
              f"achieved MOID={s['achieved_moid_km']:8.3f} km  "
              f"error={s['error_km']:+.3f} km")

    # --- automatic a/e/i adjustment demo ---
    # Ask for 50 km, which the earlier (raan, argp)-only run showed is out of reach for this altitude/inclination offset. 
    # design_orbit_auto should detect that and relax a/e/i as needed
    
    print("\n--- design_orbit_auto: requesting a distance out of reach for "
          "nominal (a, e, i) ---\n")
    d_hard = 50.0
    auto_result = design_orbit_auto(target, a_new, e_new, i_new, d_hard,
                                     grid_n=50, n_seeds=4)
    print(f"\nBest auto solution for d_desired={d_hard} km:")
    print(f"  a={auto_result['a']:.2f} km (Δ={auto_result['delta_a_km']:+.2f}), "
          f"e={auto_result['e']:.5f} (Δ={auto_result['delta_e']:+.5f}), "
          f"i={np.degrees(auto_result['i']):.3f} deg "
          f"(Δ={auto_result['delta_i_deg']:+.3f} deg)")
    print(f"  raan={auto_result['raan_deg']:.3f} deg, "
          f"argp={auto_result['argp_deg']:.3f} deg")
    print(f"  achieved MOID={auto_result['achieved_moid_km']:.3f} km "
          f"(error={auto_result['error_km']:+.3f} km)")