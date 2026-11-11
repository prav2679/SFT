import { describe, expect, it } from 'vitest';
import { coordinateError } from '../utils/coordinates';
import { buildManualBody, phaseConflict, validateTelemetry } from '../utils/telemetryValidation';
import { COLOURS, LEGEND } from '../components/Map/MapLayers';

const ok = { timestamp: '2026-11-07T10:00:00', latitude: 13.28, longitude: 80.43, altitude_m: 19500, vertical_velocity: 5.2 };

describe('coordinates are user input only', () => {
  it('rejects blank / out-of-range values instead of defaulting', () => {
    expect(coordinateError('', '', 'Launch')).toMatch(/latitude is required/);
    expect(coordinateError(13, '', 'Launch')).toMatch(/longitude is required/);
    expect(coordinateError(91, 10)).toMatch(/between/);
    expect(coordinateError(10, -181)).toMatch(/between/);
    expect(coordinateError(-33.8688, 151.2093)).toBeNull();
    expect(coordinateError(0, 0)).toBeNull();            // 0 is a valid coordinate, not "missing"
  });
});

describe('telemetry validation', () => {
  it('accepts the worked example from the specification', () => {
    expect(validateTelemetry(ok)).toEqual({});
    const body = buildManualBody({ ...ok, flight_phase: 'AUTO', reforecast: true, use_measured_ascent_rate: true, horizontal_velocity: '', wind_speed: '', wind_direction: '' });
    expect(body.timestamp_utc).toBe('2026-11-07T10:00:00Z');
    expect(body.latitude).toBe(13.28); expect(body.longitude).toBe(80.43); expect(body.altitude_m).toBe(19500);
    expect(body.horizontal_velocity).toBeNull();
  });
  it('rejects invalid timestamp, latitude, longitude and impossible altitude', () => {
    expect(validateTelemetry({ ...ok, timestamp: '' }).timestamp).toBeTruthy();
    expect(validateTelemetry({ ...ok, latitude: 90.5 }).latitude).toBeTruthy();
    expect(validateTelemetry({ ...ok, longitude: -200 }).longitude).toBeTruthy();
    expect(validateTelemetry({ ...ok, altitude_m: 75000 }).altitude_m).toBeTruthy();
    expect(validateTelemetry({ ...ok, altitude_m: -1000 }).altitude_m).toBeTruthy();
    expect(validateTelemetry({ ...ok, vertical_velocity: '' }).vertical_velocity).toBeTruthy();
    expect(validateTelemetry({ ...ok, wind_direction: 400 }).wind_direction).toBeTruthy();
  });
  it('a correction needs a reason', () => {
    expect(validateTelemetry({ ...ok, correction_of: 7, correction_reason: ' ' }).correction_reason).toBeTruthy();
    expect(validateTelemetry({ ...ok, correction_of: 7, correction_reason: 'typo' })).toEqual({});
  });
  it('flags contradictory phase / velocity', () => {
    expect(phaseConflict('ASCENT', -8)).toBeTruthy();
    expect(phaseConflict('DESCENT', 6)).toBeTruthy();
    expect(phaseConflict('FLOAT', 5)).toBeTruthy();
    expect(phaseConflict('FLOAT', 0.3)).toBeNull();
  });
});

describe('trajectory colour scheme', () => {
  it('matches the specified palette exactly', () => {
    expect(COLOURS).toMatchObject({ original: '#2979FF', actual: '#00E676', revised: '#FF9100', sft: '#AA00FF',
      tawhiri: '#FF1744', reverse: '#FFD600', diurnal: '#FFFFFF' });
  });
  it('legend rows use those colours and cover every required trajectory', () => {
    const rows = Object.values(LEGEND).flat();
    const byLabel = Object.fromEntries(rows.map((r) => [r.label, r]));
    expect(byLabel['Original Prediction'].colour).toBe('#2979FF');
    expect(byLabel['Actual Flight Path'].colour).toBe('#00E676');
    expect(byLabel['Revised Prediction'].colour).toBe('#FF9100');
    expect(byLabel['Tawhiri Prediction'].colour).toBe('#FF1744');
    expect(byLabel['Reverse Trajectory'].colour).toBe('#FFD600');
    expect(rows.find((r) => r.label.startsWith('SFT Prediction')).colour).toBe('#AA00FF');
    expect(byLabel['Actual Flight Path'].dashed).toBeFalsy();          // actual = solid
    expect(byLabel['Original Prediction'].dashed).toBe(true);          // predictions = dashed
  });
});
