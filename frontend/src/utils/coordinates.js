// Coordinates are ALWAYS user input - never defaulted, never read from the map viewport.
const isBlank = (v) => v === '' || v == null || Number.isNaN(Number(v));

/** Returns an error message, or null when both coordinates are present and in range. */
export function coordinateError(lat, lon, what = 'Launch') {
  if (isBlank(lat)) return `${what} latitude is required`;
  if (isBlank(lon)) return `${what} longitude is required`;
  if (Number(lat) < -90 || Number(lat) > 90) return `${what} latitude must be between −90° and 90°`;
  if (Number(lon) < -180 || Number(lon) > 180) return `${what} longitude must be between −180° and 180°`;
  return null;
}
