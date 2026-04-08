import { useState, useEffect, useCallback } from 'react';
import { stockApi } from '../../api/stock';
import Table from '../../components/common/Table';
import styles from './StockPage.module.css';

const MOVEMENT_LABELS = {
  PURCHASE: 'Zakup',
  SALE: 'Sprzedaż',
  ADJUSTMENT: 'Korekta',
  TRANSFER: 'Transfer',
};

// Maska ISBN: xxx-xx-xxxxxx-x-x  (13 cyfr + 4 myślniki)
function formatIsbn(raw) {
  const digits = raw.replace(/\D/g, '').slice(0, 13);
  const parts = [digits.slice(0, 3), digits.slice(3, 5), digits.slice(5, 11), digits.slice(11, 12), digits.slice(12, 13)];
  return parts.filter(Boolean).join('-');
}

const ISBN_PATTERN = /^\d{3}-\d{2}-\d{6}-\d-\d$/;

// ─── Dodaj produkt ─────────────────────────────────────────────────────────
function AddProductForm({ onAdded }) {
  const [name, setName] = useState('');
  const [isbn, setIsbn] = useState('');
  const [unit, setUnit] = useState('szt');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const handleIsbn = (e) => {
    setIsbn(formatIsbn(e.target.value));
  };

  const isbnValid = isbn === '' || ISBN_PATTERN.test(isbn);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!name.trim()) return;
    if (!isbnValid) return;
    setBusy(true);
    setError('');
    try {
      await stockApi.createProduct({ name: name.trim(), isbn: isbn.trim() || null, unit });
      setName(''); setIsbn(''); setUnit('szt');
      onAdded?.();
    } catch (err) {
      setError(
        err.response?.data?.error?.message ??
        err.response?.data?.detail ??
        'Błąd zapisu'
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={styles.card}>
      <h3 className={styles.sectionTitle}>Nowy produkt</h3>
      <form className={styles.formRow} onSubmit={handleSubmit}>
        <input
          className="input"
          placeholder="Nazwa *"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          style={{ flex: 2 }}
        />
        <input
          className="input"
          placeholder="ISBN  978-83-123456-7-8"
          value={isbn}
          onChange={handleIsbn}
          title="Format: xxx-xx-xxxxxx-x-x"
          style={{ flex: 1.5, borderColor: isbnValid ? undefined : 'var(--color-error, #e53e3e)' }}
        />
        <input
          className="input"
          placeholder="Jm (szt)"
          value={unit}
          onChange={(e) => setUnit(e.target.value)}
          style={{ flex: 1 }}
        />
        <button className="btn btn-primary" type="submit" disabled={busy || !isbnValid}>
          {busy ? <span className="spinner" /> : 'Dodaj'}
        </button>
      </form>
      {!isbnValid && (
        <div className="alert alert-error" style={{ marginTop: 8 }}>
          ISBN musi mieć format xxx-xx-xxxxxx-x-x (np. 978-83-123456-7-8)
        </div>
      )}
      {error && <div className="alert alert-error" style={{ marginTop: 8 }}>{error}</div>}
    </div>
  );
}

// ─── Ręczny ruch magazynowy ───────────────────────────────────────────────
function AddMovementForm({ products, onAdded }) {
  const [productId, setProductId] = useState('');
  const [movementType, setMovementType] = useState('PURCHASE');
  const [quantity, setQuantity] = useState('');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!productId || !quantity) return;
    setBusy(true);
    setError('');
    try {
      await stockApi.createMovement({
        product_id: productId,
        movement_type: movementType,
        quantity: parseFloat(quantity),
        note: note.trim() || null,
      });
      setQuantity(''); setNote('');
      onAdded?.();
    } catch (err) {
      setError(
        err.response?.data?.error?.message ??
        err.response?.data?.detail ??
        'Błąd zapisu'
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={styles.card}>
      <h3 className={styles.sectionTitle}>Nowy ruch magazynowy</h3>
      <form className={styles.formRow} onSubmit={handleSubmit}>
        <select
          className="input"
          value={productId}
          onChange={(e) => setProductId(e.target.value)}
          required
          style={{ flex: 2 }}
        >
          <option value="">Wybierz produkt *</option>
          {products.map((p) => (
            <option key={p.id} value={p.id}>{p.name}{p.isbn ? ` (${p.isbn})` : ''}</option>
          ))}
        </select>
        <select
          className="input"
          value={movementType}
          onChange={(e) => setMovementType(e.target.value)}
          style={{ flex: 1 }}
        >
          {Object.entries(MOVEMENT_LABELS).map(([v, l]) => (
            <option key={v} value={v}>{l}</option>
          ))}
        </select>
        <input
          className="input"
          type="number"
          step="0.0001"
          min="0.0001"
          placeholder="Ilość *"
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
          required
          style={{ flex: 1 }}
        />
        <input
          className="input"
          placeholder="Opis"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          style={{ flex: 2 }}
        />
        <button className="btn btn-primary" type="submit" disabled={busy || !productId}>
          {busy ? <span className="spinner" /> : 'Zapisz'}
        </button>
      </form>
      {error && <div className="alert alert-error" style={{ marginTop: 8 }}>{error}</div>}
    </div>
  );
}

// ─── Strona główna magazynu ───────────────────────────────────────────────
export default function StockPage() {
  const [stockItems, setStockItems] = useState([]);
  const [movements, setMovements] = useState([]);
  const [products, setProducts] = useState([]);
  const [tab, setTab] = useState('stock'); // 'stock' | 'history' | 'products'
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [s, m, p] = await Promise.all([
        stockApi.listStock(),
        stockApi.listMovements({ limit: 200 }),
        stockApi.listProducts(),
      ]);
      setStockItems(s.items ?? []);
      setMovements(m.items ?? []);
      setProducts(p);
    } catch {
      setError('Błąd ładowania danych magazynowych');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const productMap = Object.fromEntries(products.map((p) => [p.id, p]));

  const stockCols = [
    { key: 'product', label: 'Produkt', render: (_, r) => productMap[r.product_id]?.name ?? r.product_id },
    { key: 'isbn', label: 'ISBN', render: (_, r) => productMap[r.product_id]?.isbn ?? '—' },
    { key: 'quantity', label: 'Stan', render: (_, r) => `${r.quantity} ${productMap[r.product_id]?.unit ?? ''}` },
  ];

  const movCols = [
    { key: 'created_at', label: 'Data', render: (v) => new Date(v).toLocaleString('pl-PL') },
    { key: 'product', label: 'Produkt', render: (_, r) => productMap[r.product_id]?.name ?? r.product_id },
    { key: 'movement_type', label: 'Typ', render: (v) => MOVEMENT_LABELS[v] ?? v },
    { key: 'quantity', label: 'Ilość' },
    { key: 'note', label: 'Opis', render: (v) => v ?? '—' },
  ];

  const productCols = [
    { key: 'name', label: 'Nazwa' },
    { key: 'isbn', label: 'ISBN', render: (v) => v ?? '—' },
    { key: 'unit', label: 'J.m.' },
  ];

  return (
    <div className={styles.page}>
      <h1 className={styles.pageTitle}>Magazyn</h1>

      <AddProductForm onAdded={load} />
      <AddMovementForm products={products} onAdded={load} />

      <div className={styles.tabs}>
        {[['stock', 'Stan magazynu'], ['history', 'Historia ruchów'], ['products', 'Produkty']].map(([key, label]) => (
          <button
            key={key}
            className={`${styles.tab}${tab === key ? ` ${styles.tabActive}` : ''}`}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {loading ? (
        <div style={{ padding: 32, textAlign: 'center' }}><span className="spinner" /></div>
      ) : (
        <>
          {tab === 'stock' && (
            <Table columns={stockCols} rows={stockItems} emptyMsg="Brak pozycji w magazynie" />
          )}
          {tab === 'history' && (
            <Table columns={movCols} rows={movements} emptyMsg="Brak ruchów" />
          )}
          {tab === 'products' && (
            <Table columns={productCols} rows={products} emptyMsg="Brak produktów" />
          )}
        </>
      )}
    </div>
  );
}
