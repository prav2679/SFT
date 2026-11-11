"""Stage 5 SPB diurnal model: corrected vertical integration.

This is an engineering prototype, not a flight-qualified model. The atmosphere
provider is sampled at the outer timestep; within each outer step, pressure and
density are updated hydrostatically using the sampled temperature. Thermal
states are integrated at the inner timestep. Float vertical velocity is advanced
with an implicit quadratic-drag update to avoid the Stage 3 explicit-Euler
instability. No artificial velocity clipping is used.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import asin, acos, cos, exp, pi, sin, sqrt
from typing import Callable
import csv

G = 9.80665
R_HE = 2077.1
R_AIR = 287.05
SIGMA = 5.670374419e-8
SOLAR_CONSTANT = 1361.0
EARTH_RADIUS = 6_371_000.0


@dataclass
class Balloon:
    payload_mass_kg: float = 1.0
    helium_mass_kg: float = 1.2
    envelope_mass_kg: float = 3.7
    helium_cp_j_kgk: float = 5193.0
    envelope_heat_capacity_j_k: float = 7400.0
    initial_helium_temp_k: float = 301.0
    initial_envelope_temp_k: float = 301.0
    initial_volume_m3: float = 7.428
    max_volume_m3: float = 204.86
    max_differential_pressure_pa: float = 1500.0
    reference_differential_pressure_pa: float = 1000.0
    envelope_compliance_pa_inv: float = 2.0e-5
    max_expansion_fraction: float = 0.05
    solar_absorptivity: float = 0.12
    infrared_emissivity: float = 0.15
    internal_heat_transfer_w_m2k: float = 5.0
    external_h_ground_w_m2k: float = 15.0
    external_h_float_w_m2k: float = 2.0
    drag_coefficient: float = 0.45
    initial_latitude_deg: float = 13.0827
    initial_longitude_deg: float = 80.2707
    launch_elevation_m: float = 6.0
    # "compliant" uses the provisional linear P-V law; "rigid" fixes volume
    # at max_volume_m3 once the envelope becomes taut.
    envelope_mode: str = "compliant"


@dataclass
class Mission:
    launch_time_utc: datetime = datetime(2026, 10, 31, 12, 30, tzinfo=timezone.utc)
    target_float_altitude_m: float = 27000.0
    prescribed_ascent_rate_ms: float = 5.4
    float_duration_h: float = 72.0
    outer_timestep_s: float = 30.0
    inner_timestep_s: float = 1.0
    forecast_cycle: str = "2026103100"
    dataset_dir: str = "../tawhiri-data"
    solar_transmittance: float = 0.75
    sea_albedo: float = 0.06
    land_albedo: float = 0.15
    outgoing_longwave_w_m2: float = 250.0
    atmosphere_fallback: bool = False


def solar_disc_fraction(elevation_rad: float, horizon_rad: float,
                        angular_radius_rad: float = 0.00465) -> float:
    x = (elevation_rad - horizon_rad) / angular_radius_rad
    if x <= -1:
        return 0.0
    if x >= 1:
        return 1.0
    return (asin(x) + pi/2 + x*sqrt(max(0.0, 1-x*x))) / pi


def solar_geometry(lat_deg: float, lon_deg: float, altitude_m: float,
                   when: datetime):
    day = when.timetuple().tm_yday
    hour = when.hour + when.minute/60 + when.second/3600
    gamma = 2*pi/365.0 * (day - 1 + (hour - 12)/24)
    decl = (0.006918 - 0.399912*cos(gamma) + 0.070257*sin(gamma)
            - 0.006758*cos(2*gamma) + 0.000907*sin(2*gamma)
            - 0.002697*cos(3*gamma) + 0.00148*sin(3*gamma))
    eqtime = 229.18*(0.000075 + 0.001868*cos(gamma) - 0.032077*sin(gamma)
                     - 0.014615*cos(2*gamma) - 0.040849*sin(2*gamma))
    solar_minutes = hour*60 + eqtime + 4*lon_deg
    hour_angle = (solar_minutes/4 - 180)*pi/180
    lat = lat_deg*pi/180
    sin_elev = sin(lat)*sin(decl) + cos(lat)*cos(decl)*cos(hour_angle)
    elev = asin(max(-1.0, min(1.0, sin_elev)))
    horizon_depression = acos(max(-1.0, min(1.0,
        EARTH_RADIUS/(EARTH_RADIUS + max(0.0, altitude_m)))))
    return elev, solar_disc_fraction(elev, -horizon_depression)


def sphere_area(volume):
    r = (3*max(volume, 1e-9)/(4*pi))**(1/3)
    return 4*pi*r*r


def projected_area(volume):
    r = (3*max(volume, 1e-9)/(4*pi))**(1/3)
    return pi*r*r


def envelope_state(balloon: Balloon, t_he: float, p_air: float):
    """Return envelope volume and helium-to-ambient differential pressure.

    Before the envelope becomes taut, helium expands approximately freely.
    Once taut, either:
      - compliant: use the provisional linear pressure-volume relationship;
      - rigid: hold volume at max_volume_m3 and calculate differential pressure.

    Neither branch is a substitute for a measured manufacturer P-V curve.
    """
    p_air = max(p_air, 1.0)
    v_free = balloon.helium_mass_kg*R_HE*t_he/p_air
    if v_free <= balloon.max_volume_m3:
        volume = max(balloon.initial_volume_m3, v_free)
        p_inside = balloon.helium_mass_kg*R_HE*t_he/volume
        return volume, p_inside-p_air

    if balloon.envelope_mode == "rigid":
        volume = balloon.max_volume_m3
        p_inside = balloon.helium_mass_kg*R_HE*t_he/volume
        return volume, p_inside-p_air

    if balloon.envelope_mode != "compliant":
        raise ValueError("envelope_mode must be 'compliant' or 'rigid'")

    vmin = balloon.max_volume_m3*(1-balloon.max_expansion_fraction)
    vmax = balloon.max_volume_m3*(1+balloon.max_expansion_fraction)
    volume = balloon.max_volume_m3
    for _ in range(40):
        dp = balloon.helium_mass_kg*R_HE*t_he/max(volume, 1e-9)-p_air
        candidate = balloon.max_volume_m3 * (
            1 + balloon.envelope_compliance_pa_inv *
            (dp-balloon.reference_differential_pressure_pa))
        candidate = max(vmin, min(vmax, candidate))
        if abs(candidate-volume) < 1e-8:
            volume = candidate
            break
        volume = 0.5*volume + 0.5*candidate
    dp = balloon.helium_mass_kg*R_HE*t_he/max(volume, 1e-9)-p_air
    return volume, dp


def implicit_quadratic_drag_step(w, acceleration_without_drag, rho,
                                 cd, area, mass_eff, dt):
    """Solve w_new + c*w_new*abs(w_new) = w_old + a*dt."""
    q = w + acceleration_without_drag*dt
    c = 0.5*rho*cd*area*dt/max(mass_eff, 1e-9)
    if c <= 1e-15:
        return q
    magnitude = (sqrt(1 + 4*c*abs(q)) - 1)/(2*c)
    return magnitude if q >= 0 else -magnitude


def get_atmosphere(provider, lat, lon, alt, when):
    a = provider(lat, lon, alt, when)
    return (float(a["u_ms"]), float(a["v_ms"]),
            float(a["temperature_K"]), float(a["pressure_Pa"]),
            float(a["air_density_kgm3"]))


def run_simulation(provider: Callable, balloon=None, mission=None,
                   output_csv="spb_stage5_72h.csv"):
    balloon = balloon or Balloon()
    mission = mission or Mission()
    if balloon.envelope_mode not in ("compliant", "rigid"):
        raise ValueError("envelope_mode must be 'compliant' or 'rigid'")
    outer_dt = float(mission.outer_timestep_s)
    inner_dt_nominal = float(mission.inner_timestep_s)
    if outer_dt <= 0 or inner_dt_nominal <= 0:
        raise ValueError("Both timesteps must be positive.")

    lat, lon = balloon.initial_latitude_deg, balloon.initial_longitude_deg
    altitude = balloon.launch_elevation_m
    vertical_speed = 0.0
    t_he = balloon.initial_helium_temp_k
    t_env = balloon.initial_envelope_temp_k
    total_mass = (balloon.payload_mass_kg + balloon.helium_mass_kg
                  + balloon.envelope_mass_kg)
    float_elapsed = 0.0
    phase = "ascent"
    rows = []
    mission_start = mission.launch_time_utc
    float_seconds = mission.float_duration_h*3600.0
    max_seconds = ((mission.target_float_altitude_m-altitude) /
                   mission.prescribed_ascent_rate_ms + float_seconds + 600)
    n_outer = int(max_seconds/outer_dt) + 2

    for outer_index in range(n_outer):
        current_time = mission_start + timedelta(seconds=outer_index*outer_dt)

        # Record the initial state before advancing the simulation.
        u, vwind, t_air, p_ref, rho_ref = get_atmosphere(
            provider, lat, lon, altitude, current_time)
        if outer_index == 0:
            volume, dp = envelope_state(balloon, t_he, p_ref)
            elev, sun_fraction = solar_geometry(lat, lon, altitude, current_time)
            rows.append(make_row(current_time, phase, lat, lon, altitude,
                vertical_speed, u, vwind, t_air, p_ref, rho_ref, t_he, t_env,
                elev, sun_fraction, volume, dp, rho_ref*G*volume, total_mass*G))

        if phase == "float" and float_elapsed >= float_seconds:
            break

        # Atmosphere is sampled from Tawhiri at each outer step. Within this
        # interval, use a hydrostatic pressure correction as altitude changes.
        inner_count = max(1, int(round(outer_dt/inner_dt_nominal)))
        dt = outer_dt/inner_count
        base_alt = altitude
        base_pressure = p_ref
        base_temp = max(t_air, 100.0)
        scale_height = R_AIR*base_temp/G
        for j in range(inner_count):
            sub_time = current_time + timedelta(seconds=j*dt)
            elev, sun_fraction = solar_geometry(lat, lon, altitude, sub_time)
            area = sphere_area(volume if 'volume' in locals() else balloon.initial_volume_m3)
            proj = projected_area(volume if 'volume' in locals() else balloon.initial_volume_m3)
            direct = SOLAR_CONSTANT*mission.solar_transmittance*sun_fraction
            albedo = mission.sea_albedo
            q_solar = balloon.solar_absorptivity*direct*(1+0.25*albedo)*proj
            q_earth_ir = (balloon.infrared_emissivity *
                          mission.outgoing_longwave_w_m2*area*0.5)
            q_space = (balloon.infrared_emissivity*SIGMA*area*
                       (t_env**4 - 3.0**4))
            h_ext = (balloon.external_h_ground_w_m2k +
                     (balloon.external_h_float_w_m2k -
                      balloon.external_h_ground_w_m2k) *
                     min(1.0, max(0.0, altitude /
                                  mission.target_float_altitude_m)))
            q_conv = h_ext*area*(t_air-t_env)
            q_internal = (balloon.internal_heat_transfer_w_m2k *
                          area*(t_he-t_env))
            c_he = balloon.helium_mass_kg*balloon.helium_cp_j_kgk
            c_env = balloon.envelope_heat_capacity_j_k
            t_env += (q_solar+q_earth_ir-q_space+q_conv+q_internal)/c_env*dt
            t_he += (-q_internal)/max(c_he, 1.0)*dt
            t_env = min(400.0, max(100.0, t_env))
            t_he = min(400.0, max(100.0, t_he))

            # Local hydrostatic pressure/density update from altitude change.
            p_local = base_pressure*exp(-(altitude-base_alt)/scale_height)
            rho_local = p_local/(R_AIR*base_temp)
            volume, dp = envelope_state(balloon, t_he, p_local)
            buoyancy = rho_local*G*volume
            weight = total_mass*G
            if phase == "ascent":
                vertical_speed = mission.prescribed_ascent_rate_ms
                altitude += vertical_speed*dt
                if altitude >= mission.target_float_altitude_m:
                    altitude = mission.target_float_altitude_m
                    phase = "float"
                    vertical_speed = 0.0
                    float_elapsed = 0.0
            else:
                m_eff = total_mass + 0.5*rho_local*volume
                a_no_drag = (buoyancy-weight)/max(m_eff, 1e-9)
                old_vertical_speed = vertical_speed
                new_vertical_speed = implicit_quadratic_drag_step(
                    old_vertical_speed, a_no_drag, rho_local,
                    balloon.drag_coefficient, projected_area(volume),
                    m_eff, dt)
                # Trapezoidal position update: average old and new velocity.
                altitude = max(
                    0.0,
                    altitude + 0.5*(old_vertical_speed +
                                   new_vertical_speed)*dt
                )
                vertical_speed = new_vertical_speed
                float_elapsed += dt

        # Horizontal wind advection over the outer interval.
        lat += (vwind*outer_dt)/111_320.0
        lon += (u*outer_dt)/(111_320.0*max(cos(lat*pi/180), 0.05))

        # Re-sample atmosphere at the new state for a coherent output record.
        out_time = current_time + timedelta(seconds=outer_dt)
        u2, v2, ta2, p2, rho2 = get_atmosphere(
            provider, lat, lon, altitude, out_time)
        elev2, frac2 = solar_geometry(lat, lon, altitude, out_time)
        volume, dp = envelope_state(balloon, t_he, p2)
        rows.append(make_row(out_time, phase, lat, lon, altitude,
            vertical_speed, u2, v2, ta2, p2, rho2, t_he, t_env,
            elev2, frac2, volume, dp, rho2*G*volume, total_mass*G))

        if phase == "float" and float_elapsed >= float_seconds:
            break

    if not rows:
        raise RuntimeError("No simulation records generated.")
    with open(output_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return rows


def make_row(when, phase, lat, lon, altitude, w, u, vwind, t_air, p_air,
             rho_air, t_he, t_env, solar_elev, solar_fraction, volume, dp,
             buoyancy, weight):
    return {
        "time_utc": when.isoformat(), "phase": phase,
        "latitude_deg": lat, "longitude_deg": lon,
        "altitude_m": altitude, "vertical_speed_ms": w,
        "u_wind_ms": u, "v_wind_ms": vwind,
        "air_temperature_k": t_air, "air_pressure_pa": p_air,
        "air_density_kgm3": rho_air,
        "helium_temperature_k": t_he, "envelope_temperature_k": t_env,
        "solar_elevation_deg": solar_elev*180/pi,
        "solar_disc_fraction": solar_fraction,
        "envelope_volume_m3": volume,
        "differential_pressure_pa": dp,
        "buoyancy_n": buoyancy, "weight_n": weight,
        "buoyancy_margin_n": buoyancy-weight,
        "buoyancy_to_weight_ratio": buoyancy/weight if weight > 0 else float("nan"),
    }


def make_tawhiri_provider(mission):
    from tawhiri_spb_adapter import TawhiriAtmosphere
    return TawhiriAtmosphere(
        cycle=mission.forecast_cycle,
        dataset_dir=mission.dataset_dir,
        allow_isa_fallback=mission.atmosphere_fallback,
    )
