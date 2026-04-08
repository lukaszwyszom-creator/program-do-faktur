import { useState } from 'react';
import { invoicesApi } from '../../api/invoices';
import InvoiceForm from '../../components/invoice/InvoiceForm';
import InvoiceList from '../../components/invoice/InvoiceList';
import styles from './SimpleView.module.css';

export default function SimpleView() {
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const handleCreate = async (payload) => {
    setSaving(true);
    try {
      const inv = await invoicesApi.create(payload);
      setSaved(inv);
      setShowForm(false);
      setRefreshKey((k) => k + 1);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={styles.page}>
      {/* Header */}
      <div className={styles.header}>
        <div>
          <h2 className={styles.heading}>Faktury</h2>
          <p className={styles.sub}>Tryb prosty — szybkie wystawianie i zarządzanie</p>
        </div>
        <button
          className="btn btn-primary"
          onClick={() => { setShowForm((v) => !v); setSaved(null); }}
        >
          {showForm ? '✕ Anuluj' : '+ Nowa faktura'}
        </button>
      </div>

      {/* Komunikat o sukcesie */}
      {saved && !showForm && (
        <div className="alert alert-success">
          Faktura <strong>{saved.number_local ?? saved.id.slice(0, 8)}</strong> zapisana
          jako szkic. Użyj „Zatwierdź", aby oznaczyć jako gotową do wysyłki.
        </div>
      )}

      {/* Formularz */}
      {showForm && (
        <div className={styles.formWrap}>
          <InvoiceForm onSubmit={handleCreate} loading={saving} />
        </div>
      )}

      {/* Lista ostatnich 10 */}
      {!showForm && (
        <div className={styles.section}>
          <div className="card-header">
            <span className="card-title">Ostatnie faktury</span>
          </div>
          <InvoiceList
            key={refreshKey}
            limit={10}
            hidePager
            filters={{}}
          />
        </div>
      )}
    </div>
  );
}
