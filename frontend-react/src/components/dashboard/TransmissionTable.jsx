import { useState, useEffect, useCallback, useRef } from 'react';
import { transmissionsApi } from '../../api/transmissions';
import Table from '../common/Table';
import StatusBadge from '../common/StatusBadge';
import Pagination from '../common/Pagination';
import styles from './TransmissionTable.module.css';

const TERMINAL = new Set(['success', 'failed_permanent']);
const POLL_INTERVAL_MS = 8000;

function RetryBtn({ transmission, onDone, onError }) {
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      await transmissionsApi.retry(transmission.id);
      onDone();
    } catch (err) {
      onError(err.response?.data?.error?.message ?? 'Błąd retry');
    } finally {
      setBusy(false);
    }
  };
  return (
    <button className="btn btn-secondary btn-sm" disabled={busy} onClick={run}>
      {busy ? <span className="spinner" style={{ width: 12, height: 12 }} /> : 'Ponów'}
    </button>
  );
}

export default function TransmissionTable() {
  const [data, setData] = useState({ items: [], total: 0 });
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [actionMsg, setActionMsg] = useState('');
  const pollRef = useRef(null);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    setError('');
    try {
      const res = await transmissionsApi.list(page, 20);
      setData(res);
      // Zaplanuj następne odświeżenie jeśli są aktywne transmisje
      const hasActive = res.items.some((t) => !TERMINAL.has(t.status));
      if (hasActive) {
        clearTimeout(pollRef.current);
        pollRef.current = setTimeout(() => load(true), POLL_INTERVAL_MS);
      }
    } catch {
      setError('Błąd ładowania transmisji');
    } finally {
      if (!silent) setLoading(false);
    }
  }, [page]);

  useEffect(() => {
    load();
    return () => clearTimeout(pollRef.current);
  }, [load]);

  const columns = [
    {
      key: 'invoice_id',
      label: 'Faktura ID',
      width: 110,
      render: (v) => <span className={styles.mono}>{v?.slice(0, 8)}…</span>,
    },
    {
      key: 'status',
      label: 'Status',
      width: 150,
      render: (v) => <StatusBadge status={v} />,
    },
    {
      key: 'attempt_count',
      label: 'Próby',
      width: 60,
    },
    {
      key: 'ksef_reference_number',
      label: 'Ref KSeF',
      render: (v) => v ? <span className={styles.mono}>{v}</span> : <span className={styles.dash}>—</span>,
    },
    {
      key: 'error_message',
      label: 'Błąd',
      render: (v) => v
        ? <span className={styles.errText} title={v}>{v.length > 50 ? v.slice(0, 50) + '…' : v}</span>
        : <span className={styles.dash}>—</span>,
    },
    {
      key: 'updated_at',
      label: 'Aktualizacja',
      width: 150,
      render: (v) => new Date(v).toLocaleString('pl-PL'),
    },
    {
      key: '_actions',
      label: '',
      width: 80,
      render: (_, row) =>
        row.status === 'failed_retryable' ? (
          <RetryBtn
            transmission={row}
            onDone={() => { setActionMsg('Ponowiono transmisję'); load(true); }}
            onError={(m) => setActionMsg(m)}
          />
        ) : null,
    },
  ];

  return (
    <div>
      <div className={styles.toolbar}>
        <span className={styles.title}>Transmisje KSeF</span>
        <button
          className="btn btn-ghost btn-sm"
          disabled={loading}
          onClick={() => load()}
          title="Odśwież"
        >
          ↻ Odśwież
        </button>
      </div>

      {error    && <div className="alert alert-error"   style={{ marginBottom: 10 }}>{error}</div>}
      {actionMsg && <div className="alert alert-success" style={{ marginBottom: 10 }}>{actionMsg}</div>}

      <Table
        columns={columns}
        rows={data.items}
        loading={loading}
        emptyMsg="Brak transmisji"
      />
      <Pagination page={page} total={data.total} size={20} onPage={(p) => { setPage(p); }} />
    </div>
  );
}
