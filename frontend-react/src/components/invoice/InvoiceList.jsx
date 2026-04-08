import { useState, useEffect, useCallback } from 'react';
import { invoicesApi } from '../../api/invoices';
import Table from '../common/Table';
import StatusBadge from '../common/StatusBadge';
import Pagination from '../common/Pagination';
import InvoiceActions from './InvoiceActions';
import styles from './InvoiceList.module.css';

const COLUMNS = [
  { key: 'number_local', label: 'Numer', width: 160 },
  { key: 'issue_date',   label: 'Data wyst.', width: 110 },
  {
    key: 'buyer_snapshot',
    label: 'Nabywca',
    render: (v) => v?.name ?? '—',
  },
  {
    key: 'total_gross',
    label: 'Brutto',
    width: 110,
    render: (v, row) => `${Number(v).toFixed(2)} ${row.currency}`,
  },
  {
    key: 'status',
    label: 'Status',
    width: 140,
    render: (v) => <StatusBadge status={v} />,
  },
  {
    key: 'payment_status',
    label: 'Płatność',
    width: 110,
    render: (v) => <StatusBadge status={v} />,
  },
  {
    key: '_actions',
    label: '',
    width: 200,
    render: (_, row) => <InvoiceActions invoice={row} onRefresh={null} />,
  },
];

/**
 * @param {object}  filters    - aktywne filtry
 * @param {string}  direction  - 'sale' | 'purchase' (domyślnie 'sale')
 * @param {number}  limit      - max wierszy (Simple mode: 10)
 * @param {bool}    hidePager  - ukryj paginację
 * @param {Function} onSelect  - (invoice) => void
 */
export default function InvoiceList({ filters = {}, direction = 'sale', limit, hidePager = false, onSelect }) {
  const [data, setData] = useState({ items: [], total: 0 });
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);

  const size = limit ?? 20;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = {
        page,
        size,
        direction,
        ...(filters.status             && { status: filters.status }),
        ...(filters.issue_date_from    && { issue_date_from: filters.issue_date_from }),
        ...(filters.issue_date_to      && { issue_date_to: filters.issue_date_to }),
        ...(filters.contractor         && { number_filter: filters.contractor }),
      };
      const res = await invoicesApi.list(params);
      setData(res);
    } finally {
      setLoading(false);
    }
  }, [page, size, filters, direction]);

  useEffect(() => { load(); }, [load]);

  // Eksponuj reload przez ref (opcjonalnie) — proste triggery
  const columns = COLUMNS.map((col) =>
    col.key === '_actions'
      ? { ...col, render: (_, row) => <InvoiceActions invoice={row} onRefresh={load} /> }
      : col
  );

  const rows = onSelect
    ? data.items.map((inv) => ({ ...inv, _onClick: () => onSelect(inv) }))
    : data.items;

  return (
    <div>
      <Table columns={columns} rows={rows} loading={loading} emptyMsg="Brak faktur" />
      {!hidePager && (
        <Pagination page={page} total={data.total} size={size} onPage={setPage} />
      )}
    </div>
  );
}
