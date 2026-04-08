import { useState, useEffect } from 'react';
import { invoicesApi } from '../../api/invoices';
import styles from './VATSummary.module.css';

/**
 * Pobiera faktury (status=accepted + wszystkie) i agreguje VAT po stawce.
 */
export default function VATSummary({ filters }) {
  const [rows, setRows] = useState([]);
  const [totals, setTotals] = useState({ net: 0, vat: 0, gross: 0 });
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    const params = {
      page: 1,
      size: 100,
      ...(filters?.status             && { status: filters.status }),
      ...(filters?.issue_date_from    && { issue_date_from: filters.issue_date_from }),
      ...(filters?.issue_date_to      && { issue_date_to: filters.issue_date_to }),
    };
    invoicesApi
      .list(params)
      .then((res) => {
        // Agreguj po stawce VAT
        const byRate = {};
        let tNet = 0, tVat = 0;

        res.items.forEach((inv) => {
          inv.items?.forEach((item) => {
            const rate = String(item.vat_rate);
            if (!byRate[rate]) byRate[rate] = { net: 0, vat: 0 };
            byRate[rate].net += Number(item.net_total);
            byRate[rate].vat += Number(item.vat_total);
            tNet             += Number(item.net_total);
            tVat             += Number(item.vat_total);
          });
        });

        const sorted = Object.entries(byRate)
          .sort(([a], [b]) => Number(b) - Number(a))
          .map(([rate, v]) => ({ rate, ...v }));

        setRows(sorted);
        setTotals({ net: tNet, vat: tVat, gross: tNet + tVat });
      })
      .finally(() => setLoading(false));
  }, [filters]);

  if (loading) return <div className={styles.card}><span className="spinner" /></div>;

  return (
    <div className={styles.card}>
      <div className="card-header">
        <span className="card-title">Zestawienie VAT</span>
      </div>

      <table className={styles.table}>
        <thead>
          <tr>
            <th>Stawka VAT</th>
            <th>Netto</th>
            <th>Kwota VAT</th>
            <th>Brutto</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td colSpan={4} className={styles.empty}>Brak danych</td>
            </tr>
          )}
          {rows.map((r) => (
            <tr key={r.rate}>
              <td className={styles.rate}>{r.rate}%</td>
              <td>{r.net.toFixed(2)}</td>
              <td className={styles.vatCol}>{r.vat.toFixed(2)}</td>
              <td>{(r.net + r.vat).toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className={styles.totalRow}>
            <td>SUMA</td>
            <td>{totals.net.toFixed(2)}</td>
            <td className={styles.vatCol}>{totals.vat.toFixed(2)}</td>
            <td>{totals.gross.toFixed(2)}</td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
