import argparse, csv
from datetime import datetime
import matplotlib.pyplot as plt

def main():
    p = argparse.ArgumentParser()
    p.add_argument("csv_file", nargs="?", default="spb_stage5_72h.csv")
    args = p.parse_args()
    with open(args.csv_file, newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SystemExit("CSV is empty")
    t0 = datetime.fromisoformat(rows[0]["time_utc"])
    hrs = [(datetime.fromisoformat(r["time_utc"])-t0).total_seconds()/3600 for r in rows]
    series = [
        ("altitude_m", "Altitude (m)", "altitude"),
        ("vertical_speed_ms", "Vertical speed (m/s)", "vertical_speed"),
        ("helium_temperature_k", "Helium temperature (K)", "helium_temperature"),
        ("envelope_temperature_k", "Envelope temperature (K)", "envelope_temperature"),
        ("differential_pressure_pa", "Differential pressure (Pa)", "differential_pressure"),
        ("envelope_volume_m3", "Envelope volume (m³)", "envelope_volume"),
        ("solar_disc_fraction", "Solar disc visible fraction", "solar_visibility"),
        ("buoyancy_margin_n", "Buoyancy minus weight (N)", "buoyancy_margin"),
        ("buoyancy_to_weight_ratio", "Buoyancy / weight", "buoyancy_weight_ratio"),
    ]
    for key, label, filename in series:
        plt.figure()
        plt.plot(hrs, [float(r[key]) for r in rows])
        plt.xlabel("Hours since launch (UTC)")
        plt.ylabel(label)
        plt.title(label)
        plt.grid(True)
        plt.tight_layout()
        name = f"stage5_{filename}.png"
        plt.savefig(name, dpi=160)
        plt.close()
        print(f"Saved {name}")

if __name__ == "__main__":
    main()
