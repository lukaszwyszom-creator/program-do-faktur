import { useState } from 'react';
import { invoicesApi } from '../../api/invoices';
import { transmissionsApi } from '../../api/transmissions';
import styles from './InvoiceActions.module.css';

/**
 * @param {object}   invoice      - pełny obiekt faktury
 * @param {object}   transmission - opcjonalny obiekt ostatniej transmisji (dla retry)
 * @param {Function} onRefresh    - callback po akcji
 */
export default function InvoiceActions({ invoice, transmission, onRefresh }) {
  const [busy, setBusy] = useState(false);
  const [pdfBusy, setPdfBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [msgType, setMsgType] = useState('error');

  const run = async (fn, successMsg) => {
    setBusy(true);
    setMsg('');
    try {
      await fn();
      if (successMsg) { setMsg(successMsg); setMsgType('success'); }
      onRefresh?.();
    } catch (err) {
      const detail =
        err.response?.data?.error?.message ??
        err.response?.data?.detail ??
        err.response?.data?.error?.code ??
        'Błąd operacji';
      setMsg(detail);
      setMsgType('error');
    } finally {
      setBusy(false);
    }
  };

  const openPdf = async () => {
    setPdfBusy(true);
    setMsg('');
    try {
      const arrayBuffer = await invoicesApi.getPdf(invoice.id);
      const blob = new Blob([arrayBuffer], { type: 'application/pdf' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `faktura-${invoice.number_local || invoice.id}.pdf`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    } catch {
      setMsg('Błąd generowania PDF');
      setMsgType('error');
    } finally {
      setPdfBusy(false);
    }
  };

  const openPreview = async () => {
    setPdfBusy(true);
    setMsg('');
    try {
      const html = await invoicesApi.getPreview(invoice.id);
      const blob = new Blob([html], { type: 'text/html; charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const win = window.open(url, '_blank');
      if (!win) {
        setMsg('Przeglądarka zablokowała popup — zezwól na otwieranie nowych okien');
        setMsgType('error');
      }
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    } catch {
      setMsg('Błąd generowania podglądu faktury');
      setMsgType('error');
    } finally {
      setPdfBusy(false);
    }
  };

  const canMarkReady = invoice.status === 'draft';
  const canSubmit    = invoice.status === 'ready_for_submission';
  const canRetry     = transmission?.status === 'failed_retryable';

  return (
    <div className={styles.wrap}>
      {canMarkReady && (
        <button
          className="btn btn-secondary btn-sm"
          disabled={busy}
          onClick={() => run(() => invoicesApi.markReady(invoice.id), 'Gotowa do wysyłki')}
        >
          {busy ? <span className="spinner" style={{ width: 12, height: 12 }} /> : 'Zatwierdź'}
        </button>
      )}
      {canSubmit && (
        <button
          className="btn btn-primary btn-sm"
          disabled={busy}
          onClick={() => run(() => transmissionsApi.submit(invoice.id), 'Wysłano do KSeF')}
        >
          {busy ? <span className="spinner" style={{ width: 12, height: 12 }} /> : 'Wyślij KSeF'}
        </button>
      )}
      {canRetry && (
        <button
          className="btn btn-secondary btn-sm"
          disabled={busy}
          onClick={() => run(() => transmissionsApi.retry(transmission.id), 'Ponowiono')}
        >
          Ponów
        </button>
      )}
      <button
        className="btn btn-ghost btn-sm"
        disabled={pdfBusy}
        onClick={openPreview}
        title="Podgląd HTML w nowej karcie (Ctrl+P do druku)"
      >
        {pdfBusy ? <span className="spinner" style={{ width: 12, height: 12 }} /> : 'Podgląd'}
      </button>
      <button
        className="btn btn-ghost btn-sm"
        disabled={pdfBusy}
        onClick={openPdf}
        title="Pobierz jako plik PDF"
      >
        {pdfBusy ? null : 'PDF ↓'}
      </button>
      {msg && (
        <span
          className={`${styles.feedback} ${msgType === 'success' ? styles.feedbackOk : styles.err}`}
          title={msg}
        >
          {msgType === 'success' ? '✓' : '⚠'} {msg.length > 36 ? msg.slice(0, 36) + '…' : msg}
        </span>
      )}
    </div>
  );
}
