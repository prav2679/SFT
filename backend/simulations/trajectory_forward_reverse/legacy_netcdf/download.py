#!/usr/bin/env python
"""
CFSv2 6-hourly pressure-level GRIB2 downloader ONLY.

Uses the existing NOAA THREDDS catalog navigation and download logic from the
provided working script. Downloads the 21 valid-time files from the chosen
start date through +120 hours at 6-hour intervals.

No GRIB decoding, regional cropping, pressure-level filtering, NetCDF creation,
or conversion report is performed.

Region coordinates are retained as informational metadata only:
  Latitude: 2.103602 N to 15.2818 N
  Longitude: 75.141217 E to 82.4756 E

Install:
  python -m pip install beautifulsoup4
"""

import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

BASE = "https://www.ncei.noaa.gov/thredds/catalog/model-cfs-allfile-operational-forecast/6-hourly-by-pressure"
LAT_MIN, LAT_MAX = 0, 20
LON_MIN, LON_MAX = 60, 95
WINDOW_HOURS = 120
STEP_HOURS = 6
OUT_DIR = Path("hover_5days") / "grib"
OUT_DIR.mkdir(parents=True, exist_ok=True)

def http_text(url, timeout=30):
    print(f"Connecting to catalog: {url}", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            print(f"  HTTP {response.status}; reading catalog...", flush=True)
            body = response.read().decode("utf-8", errors="replace")
            print(f"  Catalog received ({len(body):,} characters).", flush=True)
            return body
    except Exception as exc:
        raise RuntimeError(f"Could not read catalog URL:\n{url}\nReason: {exc}") from exc




def parse_date(prompt):
    while True:
        value = input(prompt).strip()
        parsed = None
        for fmt in ("%Y%m%d", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(value, fmt)
                break
            except ValueError:
                pass
        if parsed:
            return parsed
        print("Invalid date. Use YYYYMMDD (20261020) or DD-MM-YYYY (20-10-2026).")




def get_inputs():
    print("\nEnter the first VALID FORECAST DATE.")
    print("Example: 17-10-2026 downloads valid times from 17 Oct 00 UTC through 22 Oct 00 UTC.")
    target_start = parse_date("Forecast start date: ")
    target_start = target_start.replace(hour=0, minute=0, second=0, microsecond=0)
    return target_start




def make_catalog_url(run_date, cycle):
    date_str = run_date.strftime("%Y%m%d")
    year, month = date_str[:4], date_str[4:6]
    run_id = date_str + cycle
    return f"{BASE}/{year}/{year}{month}/{date_str}/{run_id}/catalog.html"




def normalize_data_url(url):
    parsed = urllib.parse.urlparse(url)
    path = parsed.path
    # THREDDS HTML catalog links sometimes point to catalog paths; convert those
    # to the corresponding fileServer endpoint.
    if "/thredds/catalog/" in path:
        path = path.replace("/thredds/catalog/", "/thredds/fileServer/", 1)
    return urllib.parse.urlunparse(parsed._replace(path=path, query="", fragment=""))




def links_from_catalog(html, page_url):
    """
    Extract CFSv2 pgb files from THREDDS catalogs. The displayed link text is
    often the filename, while the href may be a dataset URL or an access link.
    """
    if not BeautifulSoup:
        raise RuntimeError("beautifulsoup4 is required. Run: python -m pip install beautifulsoup4")

    soup = BeautifulSoup(html, "html.parser")
    result = []
    seen = set()

    filename_re = re.compile(r"(pgbf\d{10}\.\d+\.\d{10}\.grb2?)", re.I)

    for tag in soup.find_all("a", href=True):
        href = urllib.parse.urljoin(page_url, tag["href"])
        visible = tag.get_text(" ", strip=True)
        href_decoded = urllib.parse.unquote(href)
        filename = None

        for candidate in (visible, href_decoded, Path(urllib.parse.urlparse(href_decoded).path).name):
            match = filename_re.search(candidate)
            if match:
                filename = match.group(1)
                break
        if not filename:
            continue

        parsed = urllib.parse.urlparse(href_decoded)
        if "/thredds/fileServer/" in parsed.path:
            direct_url = urllib.parse.urlunparse(parsed._replace(query="", fragment=""))
        else:
            # Construct the fileServer URL using the directory of the catalog page.
            cat_path = urllib.parse.urlparse(page_url).path
            marker = "/thredds/catalog/"
            if marker not in cat_path:
                continue
            relative_dir = cat_path.split(marker, 1)[1]
            relative_dir = re.sub(r"/catalog\.html$", "", relative_dir)
            direct_url = (
                "https://www.ncei.noaa.gov/thredds/fileServer/"
                + relative_dir.rstrip("/")
                + "/"
                + filename
            )

        key = (filename, direct_url)
        if key not in seen:
            seen.add(key)
            result.append((filename, direct_url))

    return result




def parse_filename(name):
    """
    Expected filename pattern:
      pgbfYYYYMMDDHH.01.YYYYMMDDCC.grb2
    First timestamp = forecast valid time; second timestamp = run initialization.
    """
    match = re.search(r"pgbf(\d{10})\.\d+\.(\d{10})\.grb2?$", name, re.I)
    if not match:
        return None, None
    try:
        valid_time = datetime.strptime(match.group(1), "%Y%m%d%H")
        run_time = datetime.strptime(match.group(2), "%Y%m%d%H")
        return valid_time, run_time
    except ValueError:
        return None, None




def download_file(url, destination):
    if destination.exists() and destination.stat().st_size > 0:
        print(f"  Already downloaded: {destination.name}")
        return
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=180) as response, destination.open("wb") as out:
            total = response.headers.get("Content-Length")
            if total:
                print(f"  Downloading {destination.name} ({int(total)/1024/1024:.1f} MiB)")
            else:
                print(f"  Downloading {destination.name}")
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    if destination.stat().st_size == 0:
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"Downloaded an empty file: {url}")




def main():
    print("=" * 72)
    print("CFSv2 120-HOUR GRIB2 DOWNLOADER ONLY")
    print("=" * 72)
    print(f"Region metadata: {LAT_MIN}–{LAT_MAX} N, {LON_MIN}–{LON_MAX} E")
    print("Coordinates are informational only; GRIB2 files are downloaded whole.")
    print("Forecast window: 120 hours, every 6 hours (21 valid timestamps, UTC).")
    print("No GRIB decoding, cropping, NetCDF conversion, or plotting.")
    print("Output folder:", OUT_DIR.resolve())

    target_start = get_inputs()
    target_end = target_start + timedelta(hours=WINDOW_HOURS)
    wanted_times = [
        target_start + timedelta(hours=h)
        for h in range(0, WINDOW_HOURS + 1, STEP_HOURS)
    ]

    by_valid = {}
    catalog_errors = []
    catalog_count = 0

    candidate_runs = []
    for back in range(0, 11):
        run_day = (target_start - timedelta(days=back)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        cycles = ("00",) if back == 0 else ("18", "12", "06", "00")
        for cycle in cycles:
            run_dt = datetime.strptime(
                run_day.strftime("%Y%m%d") + cycle, "%Y%m%d%H"
            )
            if run_dt <= target_start:
                candidate_runs.append((run_day, cycle, run_dt))

    for run_day, cycle, run_dt in candidate_runs:
        catalog_url = make_catalog_url(run_day, cycle)
        try:
            html = http_text(catalog_url, timeout=25)
            catalog_count += 1
            entries = links_from_catalog(html, catalog_url)
        except Exception as exc:
            catalog_errors.append(f"{catalog_url}: {exc}")
            continue

        candidate_by_valid = {}
        run_id = run_dt.strftime("%Y%m%d%H")
        for filename, url in entries:
            valid_dt, filename_run_dt = parse_filename(filename)
            if valid_dt is None or filename_run_dt is None:
                continue
            if filename_run_dt.strftime("%Y%m%d%H") != run_id:
                continue
            if target_start <= valid_dt <= target_end and valid_dt.hour in (0, 6, 12, 18):
                candidate_by_valid[valid_dt] = (filename, url, filename_run_dt)

        print(
            f"  Run {run_id}: found {len(candidate_by_valid)}/{len(wanted_times)} "
            "requested valid times.",
            flush=True,
        )
        if len(candidate_by_valid) > len(by_valid):
            by_valid = candidate_by_valid
        if all(dt in candidate_by_valid for dt in wanted_times):
            by_valid = candidate_by_valid
            print(f"Using single CFSv2 run {run_id} for the complete window.", flush=True)
            break

    missing = [dt for dt in wanted_times if dt not in by_valid]
    print(f"\nCatalog pages checked: {catalog_count}")
    print(
        f"Requested valid-time window: {target_start:%Y-%m-%d %H:%M} to "
        f"{target_end:%Y-%m-%d %H:%M} UTC"
    )
    print(f"Requested timestamps found: {len(wanted_times) - len(missing)}/{len(wanted_times)}")

    if missing:
        print("Missing valid times:")
        for dt in missing:
            print("  ", dt.strftime("%Y-%m-%d %H:%M UTC"))
        print("\nNot all expected times were found. No downloads started.")
        print("Last catalog errors (if any):")
        for message in catalog_errors[-5:]:
            print("  ", message)
        sys.exit(3)

    downloaded_paths = []
    for idx, valid_dt in enumerate(wanted_times, 1):
        filename, url, run_dt = by_valid[valid_dt]
        destination = OUT_DIR / filename
        print(
            f"\n[{idx}/{len(wanted_times)}] Valid {valid_dt:%Y-%m-%d %H:%M} UTC "
            f"| run {run_dt:%Y%m%d%H}",
            flush=True,
        )
        try:
            download_file(url, destination)
            downloaded_paths.append(destination)
        except Exception as exc:
            print(f"Download failed: {url}\n{exc}")
            sys.exit(4)

    print("\n" + "=" * 72)
    print("DOWNLOAD COMPLETE")
    print("=" * 72)
    print(f"Files ready: {len(downloaded_paths)}/{len(wanted_times)}")
    print("Folder:", OUT_DIR.resolve())
    print("No GRIB decoding or NetCDF conversion was run.")


if __name__ == "__main__":
    main()
