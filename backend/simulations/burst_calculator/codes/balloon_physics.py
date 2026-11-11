import math
from parameter_validation import validate_positive_finite
GRAVITY = 9.80665
R_AIR = 287.05
class Balloon:

    def __init__(
        self,
        payload_mass,
        envelope_mass,
        helium_mass,
        initial_volume,
        burst_diameter,
        drag_coefficient=0.47
    ):
        validate_positive_finite("payload_mass", payload_mass)
        validate_positive_finite("envelope_mass", envelope_mass)
        validate_positive_finite("helium_mass", helium_mass)
        validate_positive_finite("initial_volume", initial_volume)
        validate_positive_finite("burst_diameter", burst_diameter)
        validate_positive_finite("drag_coefficient", drag_coefficient)

        self.payload_mass = payload_mass
        self.envelope_mass = envelope_mass
        self.helium_mass = helium_mass
        self.initial_volume = initial_volume
        self.burst_diameter = burst_diameter
        self.drag_coefficient = drag_coefficient

    def total_mass(self):
        return (self.payload_mass+ self.envelope_mass + self.helium_mass)

    def volume_at_altitude(
        self,
        pressure_hpa,
        temperature_K,
        launch_pressure_hpa,
        launch_temperature_K
    ):
        return (
            self.initial_volume* (launch_pressure_hpa / pressure_hpa)* (temperature_K / launch_temperature_K))

    def diameter_from_volume(self, volume):
        return (6.0 * volume / math.pi) ** (1.0 / 3.0)

    def projected_area(self, volume):
        diameter = self.diameter_from_volume(volume)
        radius = diameter / 2.0
        return math.pi * radius**2

    def has_burst(self, volume):
        diameter = self.diameter_from_volume(volume)
        return diameter >= self.burst_diameter

    # Kept only as a physics/reference calculation.
    # The ascent simulation no longer uses this to determine
    # the actual climb rate.
    def theoretical_ascent_rate(
        self,
        air_density,
        pressure_hpa,
        temperature_K,
        launch_pressure_hpa,
        launch_temperature_K
    ):
        volume = self.volume_at_altitude(
            pressure_hpa,
            temperature_K,
            launch_pressure_hpa,
            launch_temperature_K
        )

        mass = self.total_mass()
        buoyancy_force = air_density * volume * GRAVITY
        weight = mass * GRAVITY
        net_force = buoyancy_force - weight

        if net_force <= 0:
            return 0.0

        area = self.projected_area(volume)

        return math.sqrt((2.0 * net_force)/ (air_density * self.drag_coefficient * area))

    # Backward-compatible alias.
    ascent_rate = theoretical_ascent_rate
