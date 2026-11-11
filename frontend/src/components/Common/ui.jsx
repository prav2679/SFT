import { useEffect, useState } from 'react';

export function Panel({ title, actions, children, tight, className = '', badge }) {
  return (
    <section className={`panel ${className}`}>
      {title && (
        <div className="panel-h"><h3>{title}</h3>{badge}<span className="spacer" />{actions}</div>
      )}
      <div className={`panel-b ${tight ? 'tight' : ''}`}>{children}</div>
    </section>
  );
}

const VC_LABEL = { MEASURED: 'MEASURED', SIMULATED: 'SIMULATED', ESTIMATE: 'MODEL EST.', FORECAST: 'FORECAST', UNAVAILABLE: 'N/A' };
export function ValueClass({ vc }) { return <span className={`badge vc-${vc}`}>{VC_LABEL[vc] || vc}</span>; }

const STATUS_CLASS = {
  CONNECTED: 's-ok', DEGRADED: 's-warn', DISCONNECTED: 's-off', AVAILABLE: 's-ok', OK: 's-ok', VALID: 's-ok',
  COMPLETED: 's-ok', RUNNING: 's-info', QUEUED: 's-info', STALE: 's-warn', NO_VALID_DATA: 's-crit', DATA_DIR_MISSING: 's-crit',
  UNREACHABLE: 's-crit', NO_DATASET: 's-warn', FAILED: 's-crit', CANCELLED: 's-off', INVALID: 's-crit', IDLE: 's-off',
  CRITICAL: 's-crit', WARNING: 's-warn', INFO: 's-info', ACTIVE: 's-ok', ABORTED: 's-crit', 'PRE-LAUNCH': 's-off',
  WEBSOCKET: 's-ok', POLLING: 's-warn', RECONNECTING: 's-warn', CONNECTING: 's-info', NONE: 's-off',
  SKIPPED_ALREADY_AVAILABLE: 's-ok', INTERRUPTED: 's-warn',
};
export function Pill({ status, children, title }) {
  return <span className={`pill ${STATUS_CLASS[status] || 's-off'}`} title={title}>{children ?? status}</span>;
}

export function Field({ label, unit, value, onChange, type = 'number', step = 'any', hint, full, options, unsupported, min, max, disabled }) {
  const id = `f-${label.replace(/\W+/g, '-')}`;
  return (
    <div className={`field ${full ? 'full' : ''} ${unsupported ? 'unsupported' : ''}`}>
      <label htmlFor={id}>{label}{unit && <span className="unit"> ({unit})</span>}</label>
      {options ? (
        <select id={id} value={value ?? ''} onChange={(e) => onChange(e.target.value)} disabled={disabled}>
          {options.map((o) => (typeof o === 'object' ? <option key={o.value} value={o.value}>{o.label}</option> : <option key={o}>{o}</option>))}
        </select>
      ) : (
        <input id={id} type={type} step={step} min={min} max={max} value={value ?? ''} disabled={disabled || unsupported}
          onChange={(e) => onChange(type === 'number' ? (e.target.value === '' ? '' : Number(e.target.value)) : e.target.value)} />
      )}
      {hint && <span className="hint">{hint}</span>}
    </div>
  );
}

export function Group({ title, children, open = true }) {
  return (
    <details className="collapsible" open={open}>
      <summary>{title}</summary>
      <div className="fields">{children}</div>
    </details>
  );
}

export function Seg({ options, value, onChange }) {
  return (
    <div className="seg" role="radiogroup">
      {options.map((o) => (
        <button key={o.value} role="radio" aria-checked={value === o.value} className={value === o.value ? 'active' : ''}
          disabled={o.disabled} title={o.title} onClick={() => onChange(o.value)}>{o.label}</button>
      ))}
    </div>
  );
}

export function KV({ items }) {
  return (
    <dl className="kv">
      {items.filter(Boolean).map(([k, v]) => [<dt key={`k${k}`}>{k}</dt>, <dd key={`v${k}`}>{v}</dd>])}
    </dl>
  );
}

export function ErrorBox({ error }) {
  if (!error) return null;
  const d = error.detail || {};
  const titles = {
    WEATHER_DATA_UNAVAILABLE: 'Weather data unavailable', TAWHIRI_ENGINE_UNAVAILABLE: 'Tawhiri engine unreachable',
    ENGINE_EXECUTION_FAILED: 'Tawhiri engine execution failed', INVALID_INPUT: 'Invalid input', MODEL_ERROR: 'Model error',
    WORKER_CRASH: 'Model worker crashed',
  };
  return (
    <div className="notice crit" role="alert">
      <b>{titles[error.errorType || d.error_type] || 'Request failed'}</b>
      <div>{error.message}</div>
      {d.checked?.length > 0 && <div className="small muted">Checked: {d.checked.join('; ')}</div>}
      {(error.errorType || d.error_type) === 'WEATHER_DATA_UNAVAILABLE' && (
        <div className="small">Download the forecast cycle that covers this window in Settings → Tawhiri weather data.</div>)}
    </div>
  );
}

export function JobStatus({ job, onCancel }) {
  if (!job) return null;
  const p = job.progress || {};
  const running = job.status === 'RUNNING' || job.status === 'QUEUED';
  return (
    <div className="stack" style={{ gap: 6 }}>
      <div className="row">
        <Pill status={job.status} />
        <span className="small muted">{job.simulation_id}{job.reused ? ' (existing result reused)' : ''}</span>
        <span className="spacer" />
        {running && onCancel && <button className="btn sm danger" onClick={onCancel}>Cancel</button>}
      </div>
      {running && (
        <div className={`progress ${p.fraction == null ? 'indeterminate' : ''}`}><div style={{ width: `${(p.fraction ?? 0) * 100}%` }} /></div>
      )}
      {p.message && running && <div className="small muted">{p.message}</div>}
      {job.status === 'FAILED' && job.error && (
        <ErrorBox error={{ message: job.error.message, errorType: job.error.error_type, detail: job.error.details || {} }} />
      )}
    </div>
  );
}

export function Tabs({ tabs, value, onChange }) {
  return (
    <nav className="subnav" aria-label="Sections">
      {tabs.map((t) => (
        <button key={t.id} className={value === t.id ? 'active' : ''} aria-current={value === t.id} onClick={() => onChange(t.id)}>
          {t.label}{t.count ? <span className="count">{t.count}</span> : null}
        </button>
      ))}
    </nav>
  );
}

export const COMPANY_NAME = 'SUSAN FUTURE TECHNOLOGY';
export const APP_NAME = 'SFT BALLOON GNC MISSION CONTROL';

/** Official SFT logo, shown unmodified (never recoloured, stretched or cropped). The supplied artwork has an
 *  opaque black background, so it is always shown on its own black badge: it stays legible on the light AND the
 *  dark interface. Height is set by CSS (`size`), width follows the intrinsic aspect ratio. */
export function Logo({ size = 'nav' }) {
  const [src, setSrc] = useState('/assets/branding/sft-logo.jpg');
  return (
    <span className={`logo-badge logo-${size}`}>
      <img src={src} alt="Susan Future Technologies logo" onError={() => setSrc('/assets/branding/sft-logo-placeholder.svg')} />
    </span>
  );
}

/** Branded strip shown at the top of every workspace. */
export function WorkspaceHeader({ title, subtitle }) {
  return (
    <div className="ws-header">
      <Logo size="header" />
      <div className="ws-header-text">
        <div className="ws-company">{COMPANY_NAME} <span>· SFT</span></div>
        <h2>{title}</h2>
        {subtitle && <div className="muted">{subtitle}</div>}
      </div>
    </div>
  );
}

/** Modal confirmation. `requireText` forces the operator to type a phrase (used for destructive bulk actions). */
export function ConfirmDialog({ open, title, children, confirmLabel = 'Confirm', danger = false, busy = false,
  requireText = null, onConfirm, onCancel }) {
  const [typed, setTyped] = useState('');
  useEffect(() => { if (!open) setTyped(''); }, [open]);
  if (!open) return null;
  const ok = !requireText || typed.trim() === requireText;
  return (
    <div className="modal-back" role="dialog" aria-modal="true" aria-label={title} onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) onCancel(); }}>
      <div className="modal">
        <h3>{title}</h3>
        <div className="modal-body">{children}</div>
        {requireText && (
          <label className="modal-type">Type <b>{requireText}</b> to continue
            <input autoFocus value={typed} onChange={(e) => setTyped(e.target.value)} aria-label="confirmation phrase" />
          </label>
        )}
        <div className="modal-actions">
          <button className="btn" onClick={onCancel} disabled={busy}>Cancel</button>
          <button className={`btn ${danger ? 'danger' : 'primary'}`} onClick={onConfirm} disabled={!ok || busy}>{busy ? 'Working…' : confirmLabel}</button>
        </div>
      </div>
    </div>
  );
}

/** Full-screen loading screen shown while the application connects to the backend. */
export function SplashScreen() {
  return (
    <div className="splash" role="status" aria-live="polite">
      <Logo size="splash" />
      <div className="splash-company">{COMPANY_NAME}</div>
      <div className="splash-app">{APP_NAME}</div>
      <div className="splash-bar"><span /></div>
      <div className="muted">Connecting to mission systems…</div>
    </div>
  );
}
