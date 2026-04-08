import { useState, useEffect, useCallback, useRef } from 'react';
import { paymentsApi } from '../../api/payments';
import { invoicesApi } from '../../api/invoices';
import Table from '../../components/common/Table';
import StatusBadge from '../../components/common/StatusBadge';
import Pagination from '../../components/common/Pagination';
import styles from './PaymentsPage.module.css';

// ─── CSV Import ──────────────────────────────────────────────────────────────
function CsvImport({ onImported }) {
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const inputRef = useRef();

  const handleFile = (e) => {
    setFile(e.target.files[0] ?? null);
    setResult(null);
    setError('');
  };

  const handleImport = async () => {
    if (!file) return;
    setBusy(true);
    setError('');
    setResult(null);
    try {
      const res = await paymentsApi.importCsv(file);
      setResult(res);
      setFile(null);
      if (inputRef.current) inputRef.current.value = '';
      onImported?.();
    } catch (err) {
      setError(
        err.response?.data?.error?.message ??
        err.response?.data?.detail ??
        'Błąd importu CSV'
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={styles.importBox}>
      <h3 className={styles.sectionTitle}>Import wyciągu CSV</h3>
      <div className={styles.importRow}>
        <input
          ref={inputRef}
          type="file"
          accept=".csv,text/csv"
          className="input"
          style={{ flex: 1 }}
          onChange={handleFile}
        />
        <button
          className="btn btn-primary"
          disabled={!file || busy}
          onClick={handleImport}
        >
          {busy ? <span className="spinner" /> : 'Importuj'}
        </button>
      </div>
      {error && <div className="alert alert-error" style={{ marginTop: 8 }}>{error}</div>}
      {result && (
        <div className="alert alert-success" style={{ marginTop: 8 }}>
          Zaimportowano: {result.imported ?? 0} · Zduplikowanych: {result.duplicates ?? 0} · Dopasowanych: {result.matched ?? 0}
        </div>
      )}
    </div>
  );
}

// ─── Allocate modal ───────────────────────────────────────────────────────────
function AllocatePanel({ transaction, onDone, onClose }) {
  const [invoiceId, setInvoiceId] = useState('');
  const [amount, setAmount] = useState(transaction?.amount ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const handleAllocate = async () => {
    setError('');
    setBusy(true);
    try {
      await paymentsApi.allocate(transaction.id, {
        invoice_id: invoiceId,
        amount: parseFloat(amount),
      });
      onDone?.();
    } catch (err) {
      setError(
        err.response?.data?.error?.message ??
        err.response?.data?.detail ??
        'Błąd alokacji'
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={styles.allocatePanel}>
      <div className={styles.allocateHeader}>
        <span>Alokuj płatność — {transaction?.title ?? transaction?.id?.slice(0, 8)}</span>
        <button className="btn btn-ghost btn-sm" onClick={onClose}>✕</button>
      </div>
      <label className={styles.fieldLabel}>ID faktury</label>
      <input
        className="input"
        type="text"
        placeholder="UUID faktury"
        value={invoiceId}
        onChange={(e) => setInvoiceId(e.target.value)}
      />
      <label className={styles.fieldLabel} style={{ marginTop: 8 }}>Kwota (PLN)</label>
      <input
        className="input"
        type="number"
        min={0}
        step="0.01"
        value={amount}
        onChange={(e) => setAmount(e.target.value)}
      />
      {error && <div className="alert alert-error" style={{ marginTop: 8 }}>{error}</div>}
      <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
        <button
          className="btn btn-primary"
          disabled={!invoiceId || busy}
          onClick={handleAllocate}
        >
          {busy ? <span className="spinner" style={{ width: 14, height: 14 }} /> : 'Alokuj'}
        </button>
        <button className="btn btn-ghost" onClick={onClose}>Anuluj</button>
      </div>
    </div>
  );
}

// ─── Transactions table ───────────────────────────────────────────────────────
export default function PaymentsPage() {
  const [data, setData] = useState({ items: [], total: 0 });
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState(null);  // transaction row being allocated
  const [rematchBusy, setRematchBusy] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await paymentsApi.listTransactions({ page, size: 20 });
      setData(res);
    } catch {
      setError('Błąd ładowania transakcji');
    } finally {
      setLoading(false);
    }
  }, [page]);

  useEffect(() => { load(); }, [load]);

  const handleRematch = async (tx) => {
    setRematchBusy(tx.id);
    try {
      await paymentsApi.rematch(tx.id);
      load();
    } catch {
      // ignoruj — następne odświeżenie pokaże aktualny stan
    } finally {
      setRematchBusy(null);
    }
  };

  const columns = [
    {
      key: 'booked_date',
      label: 'Data księgowania',
      width: 140,
      render: (v) => v ? new Date(v).toLocaleDateString('pl-PL') : '—',
    },
    {
      key: 'title',
      label: 'Tytuł',
      render: (v) => <span className={styles.titleCell} title={v}>{v}</span>,
    },
    {
      key: 'amount',
      label: 'Kwota',
      width: 110,
      render: (v) => (
        <span className={v >= 0 ? styles.positive : styles.negative}>
          {Number(v).toFixed(2)} PLN
        </span>
      ),
    },
    {
      key: 'currency',
      label: 'Waluta',
      width: 70,
    },
    {
      key: 'status',
      label: 'Status',
      width: 140,
      render: (v) => <StatusBadge status={v} />,
    },
    {
      key: '_actions',
      label: '',
      width: 160,
      render: (_, row) => (
        <div className={styles.rowBtns}>
          {row.status === 'unmatched' && (
            <button
              className="btn btn-ghost btn-sm"
              disabled={rematchBusy === row.id}
              onClick={() => handleRematch(row)}
              title="Ponownie dopasuj automatycznie"
            >
              {rematchBusy === row.id
                ? <span className="spinner" style={{ width: 12, height: 12 }} />
                : 'Auto-match'}
            </button>
          )}
          {(row.status === 'unmatched' || row.status === 'partially_matched') && (
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => setSelected(row)}
            >
              Alokuj
            </button>
          )}
        </div>
      ),
    },
  ];

  return (
    <div className={styles.page}>
      <h2 className={styles.pageTitle}>Płatności — import i rozliczenie</h2>

      <CsvImport onImported={load} />

      <div className={styles.tableSection}>
        <div className={styles.toolbar}>
          <span className={styles.sectionTitle}>Transakcje bankowe</span>
          <button className="btn btn-ghost btn-sm" disabled={loading} onClick={load}>
            ↻ Odśwież
          </button>
        </div>

        {error && <div className="alert alert-error" style={{ marginBottom: 10 }}>{error}</div>}

        <Table
          columns={columns}
          rows={data.items}
          loading={loading}
          emptyMsg="Brak transakcji. Importuj wyciąg CSV."
        />
        <Pagination page={page} total={data.total} size={20} onPage={setPage} />
      </div>

      {selected && (
        <div className={styles.overlay} onClick={() => setSelected(null)}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <AllocatePanel
              transaction={selected}
              onDone={() => { setSelected(null); load(); }}
              onClose={() => setSelected(null)}
            />
          </div>
        </div>
      )}
    </div>
  );
}
