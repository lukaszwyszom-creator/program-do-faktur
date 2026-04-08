import { useState, useEffect } from 'react';
import { contractorsApi } from '../../api/contractors';
import styles from './InvoiceForm.module.css';

const TODAY = new Date().toISOString().split('T')[0];

const EMPTY_ITEM = { name: '', quantity: '1', unit: 'szt.', unit_price_net: '', vat_rate: '23' };

const VAT_RATES = ['0', '5', '8', '23', 'zw'];

function useDebounce(value, delay) {
  const [dv, setDv] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDv(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return dv;
}

/**
 * @param {object|null} initial   - wypełnij przy edycji
 * @param {Function}    onSubmit  - (formData) => Promise
 * @param {bool}        loading
 */
export default function InvoiceForm({ initial = null, onSubmit, loading = false }) {
  const [buyerNip, setBuyerNip] = useState(initial?.buyer_snapshot?.nip ?? '');
  const [buyerInfo, setBuyerInfo] = useState(null);
  const [nipError, setNipError] = useState('');
  const [issueDate, setIssueDate] = useState(initial?.issue_date ?? TODAY);
  const [saleDate, setSaleDate] = useState(initial?.sale_date ?? TODAY);
  const [currency, setCurrency] = useState(initial?.currency ?? 'PLN');
  const [items, setItems] = useState(
    initial?.items?.map((i) => ({
      name: i.name,
      quantity: String(i.quantity),
      unit: i.unit,
      unit_price_net: String(i.unit_price_net),
      vat_rate: String(i.vat_rate),
    })) ?? [{ ...EMPTY_ITEM }]
  );
  const [error, setError] = useState('');

  const debouncedNip = useDebounce(buyerNip, 600);

  useEffect(() => {
    if (debouncedNip.length === 10) {
      setNipError('');
      contractorsApi
        .getByNip(debouncedNip)
        .then((c) => setBuyerInfo(c))
        .catch(() => {
          setBuyerInfo(null);
          setNipError('NIP nieznany — wpisz dane ręcznie lub zarejestruj kontrahenta');
        });
    } else {
      setBuyerInfo(null);
    }
  }, [debouncedNip]);

  const addItem = () => setItems((prev) => [...prev, { ...EMPTY_ITEM }]);

  const removeItem = (idx) => setItems((prev) => prev.filter((_, i) => i !== idx));

  const updateItem = (idx, field, val) =>
    setItems((prev) => prev.map((it, i) => (i === idx ? { ...it, [field]: val } : it)));

  const calcNet = (it) => {
    const q = parseFloat(it.quantity) || 0;
    const p = parseFloat(it.unit_price_net) || 0;
    return (q * p).toFixed(2);
  };

  const totalNet = items.reduce((s, it) => s + parseFloat(calcNet(it)), 0);
  const totalVat = items.reduce((s, it) => {
    const net = parseFloat(calcNet(it));
    const r = parseFloat(it.vat_rate) || 0;
    return s + (net * r) / 100;
  }, 0);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (!buyerNip || buyerNip.length !== 10) {
      setError('NIP nabywcy jest wymagany (10 cyfr)');
      return;
    }
    const parsedItems = items.map((it) => ({
      name: it.name,
      quantity: parseFloat(it.quantity),
      unit: it.unit || 'szt.',
      unit_price_net: parseFloat(it.unit_price_net),
      vat_rate: it.vat_rate === 'zw' ? 0 : parseFloat(it.vat_rate),
    }));

    if (parsedItems.some((i) => isNaN(i.quantity) || isNaN(i.unit_price_net))) {
      setError('Sprawdź ilości i ceny — nie mogą być puste');
      return;
    }

    const payload = {
      buyer_id: buyerInfo?.id ?? null,
      issue_date: issueDate,
      sale_date: saleDate,
      currency,
      items: parsedItems,
    };
    try {
      await onSubmit(payload);
    } catch (err) {
      setError(err.response?.data?.detail ?? err.response?.data?.error?.message ?? 'Błąd zapisu');
    }
  };

  return (
    <form className={styles.form} onSubmit={handleSubmit}>
      {error && <div className="alert alert-error">{error}</div>}

      {/* Nagłówek faktury */}
      <div className={styles.section}>
        <h3 className={styles.sectionTitle}>Nabywca</h3>
        <div className={styles.grid2}>
          <div className="form-group">
            <label className="form-label">NIP nabywcy *</label>
            <input
              className="input"
              type="text"
              placeholder="10 cyfr"
              maxLength={10}
              value={buyerNip}
              onChange={(e) => setBuyerNip(e.target.value.replace(/\D/g, ''))}
            />
            {nipError && <span className="form-error">{nipError}</span>}
          </div>
          <div className="form-group">
            <label className="form-label">Nabywca</label>
            <input
              className="input"
              type="text"
              readOnly
              value={buyerInfo ? `${buyerInfo.name} (${buyerInfo.city})` : ''}
              placeholder={buyerNip.length === 10 ? 'Pobieranie...' : '—'}
            />
          </div>
        </div>
      </div>

      {/* Daty */}
      <div className={styles.section}>
        <h3 className={styles.sectionTitle}>Daty i waluta</h3>
        <div className={styles.grid3}>
          <div className="form-group">
            <label className="form-label">Data wystawienia *</label>
            <input
              type="date"
              className="input"
              value={issueDate}
              onChange={(e) => setIssueDate(e.target.value)}
              required
            />
          </div>
          <div className="form-group">
            <label className="form-label">Data sprzedaży *</label>
            <input
              type="date"
              className="input"
              value={saleDate}
              onChange={(e) => setSaleDate(e.target.value)}
              required
            />
          </div>
          <div className="form-group">
            <label className="form-label">Waluta</label>
            <select
              className="select"
              value={currency}
              onChange={(e) => setCurrency(e.target.value)}
            >
              <option value="PLN">PLN</option>
              <option value="EUR">EUR</option>
              <option value="USD">USD</option>
              <option value="GBP">GBP</option>
            </select>
          </div>
        </div>
      </div>

      {/* Pozycje */}
      <div className={styles.section}>
        <div className={styles.sectionHeader}>
          <h3 className={styles.sectionTitle}>Pozycje faktury</h3>
          <button type="button" className="btn btn-ghost btn-sm" onClick={addItem}>
            + Dodaj pozycję
          </button>
        </div>

        <div className={styles.itemsHeader}>
          <span>Nazwa</span><span>Ilość</span><span>J.m.</span>
          <span>Cena netto</span><span>VAT %</span><span>Netto suma</span><span></span>
        </div>

        {items.map((it, idx) => (
          <div key={idx} className={styles.itemRow}>
            <input
              className="input"
              placeholder="Nazwa usługi/towaru"
              value={it.name}
              onChange={(e) => updateItem(idx, 'name', e.target.value)}
              required
            />
            <input
              className="input"
              type="number"
              min="0.001"
              step="0.001"
              value={it.quantity}
              onChange={(e) => updateItem(idx, 'quantity', e.target.value)}
              required
            />
            <input
              className="input"
              placeholder="szt."
              value={it.unit}
              onChange={(e) => updateItem(idx, 'unit', e.target.value)}
            />
            <input
              className="input"
              type="number"
              min="0"
              step="0.01"
              placeholder="0.00"
              value={it.unit_price_net}
              onChange={(e) => updateItem(idx, 'unit_price_net', e.target.value)}
              required
            />
            <select
              className="select"
              value={it.vat_rate}
              onChange={(e) => updateItem(idx, 'vat_rate', e.target.value)}
            >
              {VAT_RATES.map((r) => (
                <option key={r} value={r}>{r === 'zw' ? 'zw.' : `${r}%`}</option>
              ))}
            </select>
            <span className={styles.netSum}>{calcNet(it)} {currency}</span>
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={() => removeItem(idx)}
              disabled={items.length === 1}
            >
              ✕
            </button>
          </div>
        ))}

        <div className={styles.totals}>
          <span>Suma netto: <strong>{totalNet.toFixed(2)} {currency}</strong></span>
          <span>VAT: <strong>{totalVat.toFixed(2)} {currency}</strong></span>
          <span>Brutto: <strong>{(totalNet + totalVat).toFixed(2)} {currency}</strong></span>
        </div>
      </div>

      <div className={styles.actions}>
        <button type="submit" className="btn btn-primary" disabled={loading}>
          {loading ? <span className="spinner" /> : null}
          Zapisz fakturę
        </button>
      </div>
    </form>
  );
}
