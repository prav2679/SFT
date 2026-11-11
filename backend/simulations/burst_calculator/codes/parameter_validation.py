import math
from datetime import datetime
from numbers import Real


def validate_positive_finite(name, value):
    """
    Require a real, finite number strictly greater than zero.
    """

    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(
            f"{name} must be a numeric value."
        )

    if not math.isfinite(float(value)):
        raise ValueError(
            f"{name} must be finite. NaN and infinity are not allowed."
        )

    if value <= 0:
        raise ValueError(
            f"{name} must be greater than zero."
        )


def validate_finite(name, value):
    """
    Require a real, finite number. Negative values are permitted.
    """

    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(
            f"{name} must be a numeric value."
        )

    if not math.isfinite(float(value)):
        raise ValueError(
            f"{name} must be finite. NaN and infinity are not allowed."
        )


def validate_flight_parameters(parameters):
    """
    Validate all required flight parameters before simulation.
    Does not modify parameters or physics calculations.
    """

    if not isinstance(parameters, dict):
        raise ValueError("Flight parameters must be supplied as a dictionary.")

    required = [
        "latitude",
        "longitude",
        "launch_altitude",
        "launch_datetime",
        "payload_mass",
        "envelope_mass",
        "helium_mass",
        "initial_volume",
        "burst_diameter",
        "balloon_cd",
        "parachute_diameter",
        "parachute_cd",
        "ascent_rate",
        "descent_rate",
        "ascent_time_step",
        "descent_time_step",
        "burst_altitude",
        "maximum_altitude",
        "ground_altitude",
    ]

    missing = [key for key in required if key not in parameters]

    if missing:
        raise ValueError(
            f"Missing required flight parameters: {', '.join(missing)}"
        )

    # All numeric fields must be finite.
    numeric_fields = [
        "latitude",
        "longitude",
        "launch_altitude",
        "payload_mass",
        "envelope_mass",
        "helium_mass",
        "initial_volume",
        "burst_diameter",
        "balloon_cd",
        "parachute_diameter",
        "parachute_cd",
        "ascent_rate",
        "descent_rate",
        "ascent_time_step",
        "descent_time_step",
        "burst_altitude",
        "maximum_altitude",
        "ground_altitude",
    ]

    for name in numeric_fields:
        validate_finite(name, parameters[name])

    # Strictly positive physical parameters.
    positive_fields = [
        "payload_mass",
        "envelope_mass",
        "helium_mass",
        "initial_volume",
        "burst_diameter",
        "balloon_cd",
        "parachute_diameter",
        "parachute_cd",
        "ascent_rate",
        "descent_rate",
        "ascent_time_step",
        "descent_time_step",
    ]

    for name in positive_fields:
        validate_positive_finite(name, parameters[name])

    # Geographic limits.
    if not -90 <= parameters["latitude"] <= 90:
        raise ValueError("latitude must be between -90 and +90 degrees.")

    if not -180 <= parameters["longitude"] <= 180:
        raise ValueError("longitude must be between -180 and +180 degrees.")

    # Timestamp validation.
    if not isinstance(parameters["launch_datetime"], datetime):
        raise ValueError(
            "launch_datetime must be a datetime object."
        )

    # Altitude relationships.
    launch_altitude = parameters["launch_altitude"]
    burst_altitude = parameters["burst_altitude"]
    maximum_altitude = parameters["maximum_altitude"]
    ground_altitude = parameters["ground_altitude"]

    if burst_altitude <= launch_altitude:
        raise ValueError(
            "burst_altitude must be greater than launch_altitude."
        )

    if maximum_altitude <= launch_altitude:
        raise ValueError(
            "maximum_altitude must be greater than launch_altitude."
        )

    if burst_altitude > maximum_altitude:
        raise ValueError(
            "burst_altitude cannot exceed maximum_altitude."
        )

    if ground_altitude >= burst_altitude:
        raise ValueError(
            "ground_altitude must be below burst_altitude."
        )

    return True
