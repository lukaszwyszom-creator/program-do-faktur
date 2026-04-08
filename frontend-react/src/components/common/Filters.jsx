import styles from './Filters.module.css';

const INVOICE_STATUSES = [
  { value: '', label: 'Wszystkie statusy' },
  { value: 'draft', label: 'Szkic' },
  { value: 'ready_for_submission', label: 'Gotowa' },
  { value: 'sending', label: 'Wysyłanie' },
  { value: 'accepted', label: 'Zaakceptowana' },
  { value: 'rejected', label: 'Odrzucona' },
];

/**
 * @param {object}   filters   - { status, issue_date_from, issue_date_to, contractor }
 * @param {Function} onChange  - (patch) => void
 * @param {Function} onReset   - () => void
 * @param {bool}     compact   - ukryj contractor
 */
export default function Filters({ filters, onChange, onReset, compact = false }) {
  return (
    <div className={styles.bar}>
      <div className={styles.row}>
        <div className="form-group">
          <label className="form-label">Status</label>
          <select
            className="select"
            value={filters.status}
            onChange={(e) => onChange({ status: e.target.value })}
            style={{ minWidth: 160 }}
          >
            {INVOICE_STATUSES.map((s) => (
              <option key={s.value} value={s.value}>{s.label}</option>
            ))}
          </select>
        </div>

        <div className="form-group">
          <label className="form-label">Data od</label>
          <input
            type="date"
            className="input"
            value={filters.issue_date_from}
            onChange={(e) => onChange({ issue_date_from: e.target.value })}
            style={{ width: 150 }}
          />
        </div>

        <div className="form-group">
          <label className="form-label">Data do</label>
          <input
            type="date"
            className="input"
            value={filters.issue_date_to}
            onChange={(e) => onChange({ issue_date_to: e.target.value })}
            style={{ width: 150 }}
          />
        </div>

        {!compact && (
          <div className="form-group">
            <label className="form-label">Kontrahent (NIP/nazwa)</label>
            <input
              type="text"
              className="input"
              placeholder="szukaj..."
              value={filters.contractor}
              onChange={(e) => onChange({ contractor: e.target.value })}
              style={{ minWidth: 200 }}
            />
          </div>
        )}
      </div>

      <button className="btn btn-ghost btn-sm" onClick={onReset}>
        ✕ Wyczyść
      </button>
    </div>
  );
}
