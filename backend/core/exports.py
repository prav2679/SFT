"""CSV / KML export of shared-format trajectories and telemetry.

Model-native exports (the CSV/KML written by the original SFT models) are
served as-is from the job directory; these helpers cover engines/outputs
that do not write their own files (Tawhiri JSON responses, comparisons,
telemetry history).
"""
from __future__ import annotations

import csv
import io
from xml.sax.saxutils import escape

PHASE_COLOURS = {"ascent": "ff00ff00", "altitude_hold": "ffffaa00", "float": "ffffaa00",
                 "descent": "ff0000ff", "burst": "ff00ffff", "landing": "ff0000ff"}


def trajectory_csv(points: list[dict]) -> str:
    keys: list[str] = ["t", "phase", "lat", "lon", "alt", "vz"]
    for p in points:
        for k in p:
            if k not in keys and not k.startswith("_"):
                keys.append(k)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=keys, extrasaction="ignore")
    w.writeheader()
    w.writerows(points)
    return buf.getvalue()


def trajectory_kml(points: list[dict], name: str, description: str = "") -> str:
    def coords(pts):
        return " ".join(f"{p['lon']:.7f},{p['lat']:.7f},{max(p['alt'] or 0, 0):.1f}" for p in pts)

    phases: dict[str, list] = {}
    for p in points:
        phases.setdefault(p.get("phase") or "flight", []).append(p)
    parts = [f'<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
             f"<name>{escape(name)}</name><description>{escape(description)}</description>"]
    for phase, pts in phases.items():
        if len(pts) < 2:
            continue
        colour = PHASE_COLOURS.get(phase, "ff00a5ff")
        parts.append(f'<Placemark><name>{escape(phase)}</name><Style><LineStyle><color>{colour}</color>'
                     f'<width>3</width></LineStyle></Style><LineString><tessellate>1</tessellate>'
                     f'<altitudeMode>absolute</altitudeMode><coordinates>{coords(pts)}</coordinates>'
                     f'</LineString></Placemark>')
    if points:
        for label, p in (("Launch", points[0]), ("Final model point", points[-1])):
            parts.append(f"<Placemark><name>{label}</name><description>{escape(str(p.get('t')))}</description>"
                         f"<Point><altitudeMode>absolute</altitudeMode><coordinates>{p['lon']:.7f},{p['lat']:.7f},"
                         f"{max(p['alt'] or 0, 0):.1f}</coordinates></Point></Placemark>")
    parts.append("</Document></kml>")
    return "".join(parts)


def telemetry_csv(items: list[dict]) -> str:
    keys = ["timestamp_utc", "received_utc", "packet_id", "data_source", "quality", "quality_flags"]
    payload_keys: list[str] = []
    for it in items:
        for k in it["payload"]:
            if k not in payload_keys and not isinstance(it["payload"][k], dict):
                payload_keys.append(k)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(keys + payload_keys + ["derived_fields"])
    for it in items:
        w.writerow([it["timestamp_utc"], it["received_utc"], it["packet_id"], it["data_source"], it["quality"],
                    "|".join(it["quality_flags"])] + [it["payload"].get(k) for k in payload_keys]
                   + ["|".join(it.get("derived_fields", []))])
    return buf.getvalue()
