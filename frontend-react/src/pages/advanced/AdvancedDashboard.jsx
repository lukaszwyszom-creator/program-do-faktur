import { useState } from 'react';
import { useAppStore } from '../../store/useAppStore';
import DashboardSummary from '../../components/dashboard/DashboardSummary';
import VATSummary from '../../components/dashboard/VATSummary';
import TransmissionTable from '../../components/dashboard/TransmissionTable';
import KSeFSessionBar from '../../components/dashboard/KSeFSessionBar';
import InvoiceList from '../../components/invoice/InvoiceList';
import Filters from '../../components/common/Filters';
import styles from './AdvancedDashboard.module.css';

const TABS = [
  { id: 'invoices',       label: 'Faktury sprzedaży' },
  { id: 'purchase',       label: 'Faktury zakupowe' },
  { id: 'vat',            label: 'Zestawienie VAT'  },
  { id: 'transmissions',  label: 'Transmisje KSeF'   },
];

export default function AdvancedDashboard() {
  const [tab, setTab] = useState('invoices');
  const filters = useAppStore((s) => s.filters);
  const setFilters = useAppStore((s) => s.setFilters);
  const resetFilters = useAppStore((s) => s.resetFilters);

  return (
    <div className={styles.page}>
      {/* Sesja KSeF */}
      <KSeFSessionBar />

      {/* Statystyki */}
      <DashboardSummary filters={filters} />

      {/* Filtry */}
      <Filters filters={filters} onChange={setFilters} onReset={resetFilters} />

      {/* Tabsy */}
      <div className={styles.tabs}>
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`${styles.tab} ${tab === t.id ? styles.tabActive : ''}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Zawartość */}
      <div className={styles.panel}>
        {tab === 'invoices' && (
          <InvoiceList filters={filters} direction="sale" />
        )}

        {tab === 'purchase' && (
          <InvoiceList filters={filters} direction="purchase" />
        )}

        {tab === 'vat' && (
          <VATSummary filters={filters} />
        )}

        {tab === 'transmissions' && (
          <TransmissionTable />
        )}
      </div>
    </div>
  );
}
