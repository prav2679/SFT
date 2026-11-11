"""Request schemas. Field names mirror the original model interfaces so no
translation layer can silently change units or meaning."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

Lat = Field(..., ge=-90, le=90)
Lon = Field(..., ge=-180, le=180)


class BurstParameters(BaseModel):
    """Exactly the keys required by flight_model_paramaterized.run_flight()."""
    latitude: float = Lat
    longitude: float = Lon
    launch_altitude: float = Field(..., ge=-500, le=9000)
    launch_datetime: str
    payload_mass: float = Field(..., gt=0)
    envelope_mass: float = Field(..., gt=0)
    helium_mass: float = Field(..., gt=0)
    initial_volume: float = Field(..., gt=0)
    burst_diameter: float = Field(..., gt=0)
    balloon_cd: float = Field(..., gt=0)
    parachute_diameter: float = Field(..., gt=0)
    parachute_cd: float = Field(..., gt=0)
    ascent_rate: float = Field(..., gt=0)
    descent_rate: float = Field(..., gt=0)
    ascent_time_step: float = Field(..., gt=0)
    descent_time_step: float = Field(..., gt=0)
    burst_altitude: float = Field(..., gt=0)
    maximum_altitude: float = Field(..., gt=0)
    ground_altitude: float = Field(..., ge=-500)

    @model_validator(mode="after")
    def check(self):
        if self.burst_altitude <= self.launch_altitude:
            raise ValueError("burst_altitude must be greater than launch_altitude")
        if self.burst_altitude > self.maximum_altitude:
            raise ValueError("burst_altitude cannot exceed maximum_altitude (safety ceiling)")
        if self.ground_altitude >= self.burst_altitude:
            raise ValueError("ground_altitude must be below burst_altitude")
        return self


class BurstRequest(BaseModel):
    parameters: BurstParameters
    forecast_cycle: Optional[str] = None
    force: bool = False


class ForwardParameters(BaseModel):
    """Keys of flight_forward.simulate_mission()."""
    launch_latitude: float = Lat
    launch_longitude: float = Lon
    launch_altitude_m: float = Field(0.0, ge=-500, le=9000)
    launch_datetime: str
    hold_duration_hours: float = Field(..., gt=0, le=180)
    payload_mass_kg: float = Field(..., gt=0)
    parachute_diameter_m: float = Field(..., gt=0)
    parachute_cd: float = Field(1.5, gt=0)
    target_altitude_m: float = Field(..., gt=0, le=50000)
    ascent_rate_mps: float = Field(..., gt=0)
    ascent_hold_step_s: float = Field(60.0, gt=0)
    descent_output_step_s: float = Field(10.0, gt=0)
    ground_altitude_m: float = Field(0.0, ge=-500)


class ReverseParameters(BaseModel):
    """Keys of flight_backtrack.backtrack_landing()."""
    target_latitude: float = Lat
    target_longitude: float = Lon
    target_landing_datetime: str
    target_altitude_m: float = Field(25000.0, gt=0, le=50000)
    hold_duration_hours: float = Field(50 / 60, ge=0, le=180)
    launch_altitude_m: float = Field(0.0, ge=-500)
    ascent_rate_mps: float = Field(6.69, gt=0)
    payload_mass_kg: float = Field(5.0, gt=0)
    parachute_diameter_m: float = Field(2.4, gt=0)
    parachute_cd: float = Field(1.0, gt=0)
    ground_altitude_m: float = Field(0.0, ge=-500)
    backtrack_step_s: float = Field(60.0, gt=0)
    ascent_hold_step_s: float = Field(60.0, gt=0)
    descent_output_step_s: float = Field(10.0, gt=0)


class TrajectoryRequest(BaseModel):
    engine: Literal["sft", "tawhiri", "compare"] = "sft"
    sft_model: Literal["hold_mission", "burst_flight"] = "hold_mission"
    forward: Optional[ForwardParameters] = None
    burst: Optional[BurstParameters] = None
    reverse: Optional[ReverseParameters] = None
    tawhiri_descent_rate: Optional[float] = Field(None, gt=0, description="Sea-level descent rate for Tawhiri standard profile")
    forecast_cycle: Optional[str] = None
    force: bool = False


class DiurnalRequest(BaseModel):
    balloon: dict[str, Any] = {}
    mission: dict[str, Any] = {}
    forecast_cycle: Optional[str] = None
    force: bool = False


class MissionCreate(BaseModel):
    mission_id: Optional[str] = None
    balloon_id: str = "SFT-SPB-01"
    mission_name: str
    mode: Literal["LIVE", "SIMULATION"]
    launch_time: Optional[str] = None
    launch_latitude: Optional[float] = Field(None, ge=-90, le=90)
    launch_longitude: Optional[float] = Field(None, ge=-180, le=180)
    launch_altitude: Optional[float] = None
    config: dict[str, Any] = {}

    @model_validator(mode="after")
    def need_launch_position(self):
        if self.launch_latitude is None or self.launch_longitude is None:
            raise ValueError("launch_latitude and launch_longitude are required - they are never defaulted")
        return self


class MissionUpdate(BaseModel):
    mission_name: Optional[str] = None
    launch_time: Optional[str] = None
    launch_latitude: Optional[float] = Field(None, ge=-90, le=90)
    launch_longitude: Optional[float] = Field(None, ge=-180, le=180)
    launch_altitude: Optional[float] = None
    config: Optional[dict[str, Any]] = None


class AttachPrediction(BaseModel):
    simulation_id: str


class SimulationStart(BaseModel):
    source: str = "recorded"            # recorded | burst:<id> | forward:<id> | diurnal:<id>
    speed: float = Field(10.0, gt=0, le=500)
    interval_s: float = Field(10.0, ge=1, le=600)
    gps_noise_m: float = Field(0.0, ge=0, le=500)
    prelaunch_s: float = Field(60.0, ge=0, le=3600)
    attach_prediction: bool = True
    scenarios: list[dict[str, Any]] = []
    seed: int = 42


class TelemetryPacket(BaseModel):
    mission_id: str
    packet_id: str | int
    timestamp_utc: str
    data_source: Literal["MEASURED", "SIMULATED"]
    payload: dict[str, Any]
    units: Optional[dict[str, str]] = None


class ReforecastRequest(BaseModel):
    """Legacy (simulation_id + optional telemetry dict -> ascent-only LiveTrajectoryManager) and the phase-aware
    request (telemetry_id / phase / float_end_datetime -> new prediction version). Fields are additive."""
    simulation_id: Optional[str] = Field(None, description="Completed burst-calculator job providing the baseline")
    telemetry: Optional[dict[str, Any]] = Field(None, description="Legacy override; default = latest valid telemetry")
    telemetry_id: Optional[int] = Field(None, description="Re-forecast from this stored telemetry record")
    phase: Optional[Literal["AUTO", "ASCENT", "FLOAT", "DESCENT"]] = "AUTO"
    float_end_datetime: Optional[str] = None
    hold_duration_hours: Optional[float] = Field(None, gt=0)
    use_measured_ascent_rate: bool = True
    forecast_cycle: Optional[str] = None


class ManualTelemetry(BaseModel):
    """Operator-entered observed state. Units: degrees, metres, m/s; wind direction is the direction wind blows FROM."""
    timestamp_utc: str
    latitude: float
    longitude: float
    altitude_m: float
    vertical_velocity: float
    horizontal_velocity: Optional[float] = None
    wind_speed: Optional[float] = None
    wind_direction: Optional[float] = None
    flight_phase: Literal["AUTO", "ASCENT", "FLOAT", "DESCENT", "LANDED"] = "AUTO"
    correction_of: Optional[int] = None
    correction_reason: Optional[str] = None
    reforecast: bool = True
    baseline_simulation_id: Optional[str] = None
    float_end_datetime: Optional[str] = None
    hold_duration_hours: Optional[float] = Field(None, gt=0)
    use_measured_ascent_rate: bool = True
    forecast_cycle: Optional[str] = None


class DownloadRequest(BaseModel):
    cycle: str
    force: bool = False
