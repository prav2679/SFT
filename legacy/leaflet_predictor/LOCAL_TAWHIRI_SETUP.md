# Run this Leaflet frontend with your local Tawhiri engine

This is the CUSF/SondeHub Leaflet predictor frontend, configured to send predictions to the **local Tawhiri API**, not the public SondeHub API. The small `local_frontend_server.py` serves the static site and proxies `/api/v1/` requests to Tawhiri, avoiding browser CORS issues.

## 1. Start Tawhiri (Terminal 1, WSL)

```bash
cd ~/projects/tawhiri-master
source .venv310/bin/activate
export TAWHIRI_SETTINGS="$PWD/local_settings.py"
tawhiri-webapp runserver
```

Keep this terminal running. It should listen at `http://127.0.0.1:5000/`.

## 2. Start the frontend (Terminal 2, WSL)

Extract this ZIP in WSL, then run:

```bash
cd ~/projects/leaflet_predictor-master
python3 local_frontend_server.py
```

Open **http://127.0.0.1:8080** in your browser. Do not open `index.html` directly as a `file://` URL.

## 3. Test with the dataset you already downloaded

The proxy defaults to dataset initialization `2026-10-02T00:00:00Z`, matching `~/projects/tawhiri-data/2026100200`. Choose a launch date/time inside the data's valid window (2026-10-02 00:00 UTC through 2026-10-10 00:00 UTC). Example: launch on **2 October 2026 at 06:00 UTC**. Set Chennai coordinates, launch altitude 6 m, ascent rate 5 m/s, burst altitude 30000 m, descent rate 5 m/s, then click **Run Prediction**.

If you later use a different initialized dataset, start the frontend server with the matching dataset timestamp, for example:

```bash
TAWHIRI_DATASET=2026-10-03T00:00:00Z python3 local_frontend_server.py
```

The dataset value must correspond to a dataset available under `WIND_DATASET_DIR`; it is not automatically inferred from the launch date.

## Notes / limitations

- This UI is the existing CUSF latex sounding-balloon predictor. It supports the standard ascent/burst/descent profile and the legacy float options exposed by the frontend. It is not yet the custom super-pressure balloon GNC controller with altitude-hold, active altitude selection, or target-waypoint control.
- The final model trajectory point may still be above ground level; treat it as the model's last point, not guaranteed ground contact.
- This frontend still contains legacy airspace/NOTAM and PHP-era references that are not required for the main local Tawhiri prediction path.
- The frontend uses Leaflet/OpenStreetMap tiles, so no Google Maps API key is needed.
