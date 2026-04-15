import styles from './Filters.module.css';

const INVOICE_STATUSES = [
  { value: '', label: 'Wszystkie statusy' },
  { value: 'draft', label: 'Szkic' },
  { value: 'ready_for_submission', label: 'Gotowa' },
  { value: 'sending', label: 'Wysyłanie' },
  { value: 'accepted', label: 'Zaakceptowana' },
  { value: 'rejected', label: 'Odrzucona' },
];

function buildYearOptions() {
  const cur = new Date().getFullYear();
  return [cur - 2, cur - 1, cur, cur + 1].map((y) => ({ value: String(y), label: String(y) }));
}

const YEAR_OPTIONS = buildYearOptions();

const MONTHS_OF_YEAR = [
  { value: '01', label: 'styczeń' },
  { value: '02', label: 'luty' },
  { value: '03', label: 'marzec' },
  { value: '04', label: 'kwiecień' },
  { value: '05', label: 'maj' },
  { value: '06', label: 'czerwiec' },
  { value: '07', label: 'lipiec' },
  { value: '08', label: 'sierpień' },
  { value: '09', label: 'wrzesień' },
  { value: '10', label: 'październik' },
  { value: '11', label: 'listopad' },
  { value: '12', label: 'grudzień' },
];

/**
 * @param {object}   filters   - { month, status, issue_date_from, issue_date_to, contractor }
 * @param {Function} onChange  - (patch) => void
 * @param {Function} onReset   - () => void
 * @param {bool}     compact   - ukryj contractor
 */
export default function Filters({ filters, onChange, onReset, compact = false }) {
  const now = new Date();
  const nowYear  = now.getFullYear();
  const nowMonth = now.getMonth() + 1; // 1-12

  const [filterYear, filterMonth] = (filters.month ?? '').split('-');
  const selectedYear = filterYear ? Number(filterYear) : null;

  // Jeśli wybrany rok jest przyszłyś i aktualnie wybrany miesiąc jeszcze nie
  // nastąpił, automatycznie korygujemy na bieżący miesiąc.
  const handleYear = (e) => {
    const yr = e.target.value;
    if (!yr) { onChange({ month: '', issue_date_from: '', issue_date_to: '' }); return; }
    const yrNum = Number(yr);
    let m = filterMonth || String(nowMonth).padStart(2, '0');
    if (yrNum > nowYear || (yrNum === nowYear && Number(m) > nowMonth)) {
      m = String(nowMonth).padStart(2, '0');
    }
    onChange({ month: `${yr}-${m}`, issue_date_from: '', issue_date_to: '' });
  };
  const handleMonth = (e) => onChange({ month: `${filterYear || nowYear}-${e.target.value}`, issue_date_from: '', issue_date_to: '' });
  const handleDateFrom = (e) => onChange({ issue_date_from: e.target.value, month: '' });
  const handleDateTo   = (e) => onChange({ issue_date_to: e.target.value, month: '' });

  return (
    <div className={styles.bar}>
      <div className={styles.row}>
        <div className="form-group">
          <label className="form-label">Rok</label>
          <select
            className="select"
            value={filterYear ?? ''}
            onChange={handleYear}
            style={{ minWidth: 90 }}
          >
            <option value="">---</option>
            {YEAR_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>

        <div className="form-group">
          <label className="form-label">Miesiąc</label>
          <select
            className="select"
            value={filterMonth ?? ''}
            onChange={handleMonth}
            style={{ minWidth: 140 }}
          >
            <option value="">---</option>
            {MONTHS_OF_YEAR.map((o) => {
              // Ciemnoszary kolor dla miesięcy które jeszcze nie nastąpiły w wybranym roku
              const isFuture = selectedYear !== null && (
                selectedYear > nowYear ||
                (selectedYear === nowYear && Number(o.value) > nowMonth)
              );
              return (
                <option
                  key={o.value}
                  value={o.value}
                  style={isFuture ? { color: '#888', fontStyle: 'italic' } : undefined}
                >
                  {o.label}
                </option>
              );
            })}
          </select>
        </div>

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
            onChange={handleDateFrom}
            style={{ width: 150 }}
          />
        </div>

        <div className="form-group">
          <label className="form-label">Data do</label>
          <input
            type="date"
            className="input"
            value={filters.issue_date_to}
            onChange={handleDateTo}
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
