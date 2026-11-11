"""
Baseline SPB parameters transcribed from spb_balloon_parameters.xlsx.
Values marked "assumed" must be calibrated before treating trajectory results as validated.
"""

PARAMETERS = {
    # Balloon / mission-independent physical properties
    "payload_mass_kg": 1.0,                 # Given
    "helium_mass_kg": 1.2,                  # Given
    "envelope_mass_kg": 3.7,                # Assumed estimate
    "helium_gas_constant_J_kgK": 2077.0,    # Calculated/standard
    "air_gas_constant_J_kgK": 287.05,       # Calculated/standard
    "ground_pressure_Pa": 101000.0,         # Assumed
    "initial_helium_temperature_K": 301.0,  # Assumed
    "initial_envelope_temperature_K": 301.0,# Assumed
    "initial_helium_volume_m3": 7.427846,   # Calculated from mRT/P
    "minimum_volume_m3": 7.427846,           # Assumed
    "maximum_volume_m3": 204.861111,         # Calculated neutral-buoyancy estimate at 27 km
    "maximum_differential_pressure_Pa": 1500.0, # Assumed
    "target_float_altitude_m": 27000.0,     # Given
    "nominal_ascent_rate_m_s": 5.4,         # Given
    "drag_coefficient": 0.45,               # Assumed

    # SPB envelope mechanics
    "reference_differential_pressure_Pa": 1000.0, # Assumed
    "volume_compliance_per_Pa": 2.0e-5,     # Assumed; ~2% per kPa
    "maximum_compliance_expansion_fraction": 0.05, # Assumed; interpretation needs confirmation

    # Thermal / optical properties
    "solar_absorptivity": 0.12,              # Assumed
    "infrared_emissivity": 0.15,             # Assumed
    "envelope_effective_heat_capacity_J_K": 7400.0, # Calculated from envelope mass * cp
    "internal_heat_transfer_W_m2K": 5.0,    # Assumed
    "external_h_ground_W_m2K": 15.0,        # Assumed
    "external_h_27km_W_m2K": 2.0,           # Assumed

    # Solar / environmental model
    "solar_constant_W_m2": 1361.0,          # Assumed standard value
    "sea_level_transmittance": 0.75,        # Assumed
    "land_albedo": 0.15,                    # Assumed
    "sea_albedo": 0.06,                     # Assumed
    "low_cloud_albedo": 0.50,               # Assumed
    "high_cloud_albedo": 0.80,              # Assumed
    "outgoing_longwave_W_m2": 250.0,        # Assumed tropical value

    # Gas / film thermal properties
    "helium_cp_J_kgK": 5193.0,              # Assumed
    "helium_cv_J_kgK": 3116.0,              # Assumed
    "helium_envelope_heat_transfer_W_m2K": 5.0, # Assumed
    "envelope_cp_J_kgK": 2000.0,            # Assumed
    "envelope_thickness_m": 20e-6,          # Assumed
    "envelope_conductivity_W_mK": 0.4,      # Assumed
    "envelope_material": "PXO3",            # Given label; properties not datasheet-verified
}

SOURCE_STATUS = {
    "given": [
        "payload_mass_kg", "helium_mass_kg",
        "target_float_altitude_m", "nominal_ascent_rate_m_s",
        "envelope_material",
    ],
    "assumed": [
        "envelope_mass_kg", "ground_pressure_Pa",
        "initial_helium_temperature_K", "initial_envelope_temperature_K",
        "minimum_volume_m3", "maximum_differential_pressure_Pa",
        "drag_coefficient", "reference_differential_pressure_Pa",
        "volume_compliance_per_Pa", "maximum_compliance_expansion_fraction",
        "solar_absorptivity", "infrared_emissivity",
        "internal_heat_transfer_W_m2K", "external_h_ground_W_m2K",
        "external_h_27km_W_m2K", "solar_constant_W_m2",
        "sea_level_transmittance", "land_albedo", "sea_albedo",
        "low_cloud_albedo", "high_cloud_albedo", "outgoing_longwave_W_m2",
        "helium_cp_J_kgK", "helium_cv_J_kgK",
        "helium_envelope_heat_transfer_W_m2K", "envelope_cp_J_kgK",
        "envelope_thickness_m", "envelope_conductivity_W_mK",
    ],
    "calculated_or_standard": [
        "helium_gas_constant_J_kgK", "air_gas_constant_J_kgK",
        "initial_helium_volume_m3", "maximum_volume_m3",
        "envelope_effective_heat_capacity_J_K",
    ],
}

def validate_parameters(p=PARAMETERS):
    """Return warnings; does not silently alter spreadsheet values."""
    warnings = []
    if p["helium_mass_kg"] <= 0 or p["initial_helium_volume_m3"] <= 0:
        warnings.append("Helium mass and initial volume must be positive.")
    if not 0 < p["solar_absorptivity"] <= 1:
        warnings.append("Solar absorptivity must be in (0, 1].")
    if not 0 < p["infrared_emissivity"] <= 1:
        warnings.append("IR emissivity must be in (0, 1].")
    if p["minimum_volume_m3"] >= p["maximum_volume_m3"]:
        warnings.append("Minimum volume must be below maximum volume.")

    # Explicit spreadsheet consistency warning:
    # 5% expansion and 7.43 -> 204.86 m3 are different concepts/scales.
    geometric_expansion = (
        p["maximum_volume_m3"] / p["initial_helium_volume_m3"] - 1.0
    )
    if geometric_expansion > p["maximum_compliance_expansion_fraction"]:
        warnings.append(
            "Spreadsheet interpretation conflict: Vmax is about "
            f"{100*geometric_expansion:.1f}% above V0, while the separate "
            "maximum-compliance-expansion entry is 5%. These cannot both mean "
            "the total allowable expansion from V0. Confirm whether 5% limits "
            "elastic compliance around the fully inflated reference volume."
        )

    # The spreadsheet derives V0 from ideal gas law at the stated ground pressure.
    calculated_v0 = (
        p["helium_mass_kg"]
        * p["helium_gas_constant_J_kgK"]
        * p["initial_helium_temperature_K"]
        / p["ground_pressure_Pa"]
    )
    relative_error = abs(calculated_v0 - p["initial_helium_volume_m3"]) / calculated_v0
    if relative_error > 0.02:
        warnings.append(
            "Initial helium volume differs by more than 2% from ideal-gas "
            "recalculation using the current mass, temperature and pressure."
        )
    return warnings

if __name__ == "__main__":
    print("SPB baseline parameter set")
    print("==========================")
    for key, value in PARAMETERS.items():
        print(f"{key:48s} {value}")
    issues = validate_parameters()
    print("\nValidation:")
    if issues:
        for issue in issues:
            print("WARNING:", issue)
    else:
        print("No validation warnings.")
