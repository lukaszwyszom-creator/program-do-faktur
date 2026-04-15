import { useState, useEffect, useMemo } from 'react';
import {
  AreaChart, Area,
  XAxis, YAxis, Tooltip,
  ResponsiveContainer, CartesianGrid,
} from 'recharts';
import { invoicesApi } from '../../api/invoices';
import styles from './DashboardSummary.module.css';

const METRICS = [
  { key: 'total',    label: 'Wszystkich faktur',   cls: 'neutral' },
  { key: 'accepted', label: 'Zaakceptowanych',     cls: 'success' },
  { key: 'ready',    label: 'Gotowych do wysyłki', cls: 'info'    },
  { key: 'draft',    label: 'Szkiców',             cls: 'neutral' },
  { key: 'rejected', label: 'Odrzuconych',         cls: 'error'   },
];

// ---- helpers ----
function currentMonthPrefix() {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, '0');
  return `${y}-${m}`;
}

function monthLabel(prefix) {
  if (!prefix) return '';
  const [y, m] = prefix.split('-');
  const d = new Date(Number(y), Number(m) - 1, 1);
  return d.toLocaleDateString('pl-PL', { year: 'numeric', month: 'long' });
}

function buildDailyMap(invoices) {
  // Zlicza wartości w PLN: faktury PLN bezpośrednio, waluty obce × exchange_rate
  const map = {};
  for (const inv of invoices) {
    const d = (inv.issue_date ?? '').toString().slice(0, 10);
    if (!d) continue;
    const gross = parseFloat(inv.total_gross ?? 0) || 0;
    if (!gross) continue;
    const currency = (inv.currency ?? 'PLN').toUpperCase();
    let plnAmount;
    if (currency === 'PLN') {
      plnAmount = gross;
    } else {
      const rate = parseFloat(inv.exchange_rate ?? 0) || 0;
      if (!rate) continue; // waluta obca bez kursu — pomijamy na wykresie
      plnAmount = gross * rate;
    }
    map[d] = (map[d] ?? 0) + plnAmount;
  }
  return map;
}

// Zwraca sumę walut obcych: { EUR: { grossForeign, grossPln }, USD: {...} }
function buildForeignSummary(invoices) {
  const acc = {};
  for (const inv of invoices) {
    const cur = inv.currency ?? 'PLN';
    if (cur === 'PLN') continue;
    const gross = Number(inv.total_gross ?? 0);
    const rate  = Number(inv.exchange_rate ?? 0);
    if (!acc[cur]) acc[cur] = { grossForeign: 0, grossPln: 0 };
    acc[cur].grossForeign = +(acc[cur].grossForeign + gross).toFixed(2);
    acc[cur].grossPln     = +(acc[cur].grossPln + gross * rate).toFixed(2);
  }
  return acc;
}

async function fetchNbpRate(currency) {
  try {
    const resp = await fetch(
      `https://api.nbp.pl/api/exchangerates/rates/a/${currency}/?format=json`,
      { headers: { Accept: 'application/json' } },
    );
    if (!resp.ok) return null;
    const data = await resp.json();
    return Number(data.rates?.[0]?.mid ?? null);
  } catch {
    return null;
  }
}

function buildCombinedData(saleMap, purchaseMap) {
  const allDays = [...new Set([...Object.keys(saleMap), ...Object.keys(purchaseMap)])].sort();
  let cumSale = 0;
  let cumPurchase = 0;
  return allDays.map((date) => {
    cumSale     = +(cumSale     + (saleMap[date]     ?? 0)).toFixed(2);
    cumPurchase = +(cumPurchase + (purchaseMap[date] ?? 0)).toFixed(2);
    return {
      date:         date.slice(8, 10),
      fullDate:     date,
      cumSale,
      cumPurchase,
      dailySale:     +((saleMap[date]     ?? 0).toFixed(2)),
      dailyPurchase: +((purchaseMap[date] ?? 0).toFixed(2)),
    };
  });
}

// ---- tooltip łączony ----
function CombinedTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const pt = payload[0].payload;
  return (
    <div className={styles.tooltip}>
      <div className={styles.tooltipDate}>{pt.fullDate}</div>
      <div className={styles.tooltipValue}>
        Sprzedaż: {pt.cumSale.toLocaleString('pl-PL', { minimumFractionDigits: 2 })} PLN
        {pt.dailySale > 0 && (
          <span className={styles.tooltipSubInline}> (+{pt.dailySale.toLocaleString('pl-PL', { minimumFractionDigits: 2 })})</span>
        )}
      </div>
      <div className={styles.tooltipValueBlue}>
        Zakupy: {pt.cumPurchase.toLocaleString('pl-PL', { minimumFractionDigits: 2 })} PLN
        {pt.dailyPurchase > 0 && (
          <span className={styles.tooltipSubInline}> (+{pt.dailyPurchase.toLocaleString('pl-PL', { minimumFractionDigits: 2 })})</span>
        )}
      </div>
    </div>
  );
}

// Mapowanie wartości filtrów na etykiety po polsku
const STATUS_LABELS = {
  draft:                 'szkic',
  ready_for_submission:  'gotowa',
  sending:               'wysyłanie',
  accepted:              'zaakceptowana',
  rejected:              'odrzucona',
};

const TAB_LABELS = {
  invoices:      'sprzedaż',
  purchase:      'zakupy',
  vat:           'VAT',
  transmissions: 'transmisje KSeF',
};

export default function DashboardSummary({ filters, tab }) {
  const [stats, setStats]           = useState({ total: 0, accepted: 0, ready: 0, draft: 0, rejected: 0 });
  const [statsLoading, setStatsLoading] = useState(false);

  // Jeden atomowy stan wykresu — eliminuje race-condition między
  // setAllSale/setAllPurchase (.then) a setChartLoading (.finally)
  const [chart, setChart] = useState({
    loading:         true,
    saleInvoices:    [],
    purchaseInvoices: [],
    currentRates:    {},
  });

  // Wyznacz prefix miesiąca z filtrów lub bieżący miesiąc
  // Zakres dat z pola miesiąca (fallback na bieżący miesiąc)
  const prefix    = filters?.month || currentMonthPrefix();
  const monthFrom = `${prefix}-01`;
  const monthTo   = (() => {
    const [y, m] = prefix.split('-').map(Number);
    const last = new Date(y, m, 0).getDate();
    return `${prefix}-${String(last).padStart(2, '0')}`;
  })();

  // Ręczny zakres dat (nadpisuje miesiąc)
  const dateFrom        = filters?.issue_date_from || '';
  const dateTo          = filters?.issue_date_to   || '';
  const dateRangeActive = !!(dateFrom || dateTo);

  // Efektywny zakres dat do fetchowania
  const effectFrom = dateRangeActive ? dateFrom : monthFrom;
  const effectTo   = dateRangeActive ? dateTo   : monthTo;

  // Etykieta okresu do prawego górnego rogu
  const periodLabel = dateRangeActive
    ? `${dateFrom || '...'} – ${dateTo || '...'}`
    : monthLabel(prefix);

  // Etykieta opcji (status + kontrahent)
  const optsLabel = [
    filters?.status     ? (STATUS_LABELS[filters.status] || filters.status) : '',
    filters?.contractor || '',
  ].filter(Boolean).join(', ');

  // Karty metryk (globalne liczniki, niezależne od filtrów)
  useEffect(() => {
    let cancelled = false;
    setStatsLoading(true);
    Promise.all([
      invoicesApi.list({ page: 1, size: 1 }),
      invoicesApi.list({ page: 1, size: 1, status: 'accepted' }),
      invoicesApi.list({ page: 1, size: 1, status: 'ready_for_submission' }),
      invoicesApi.list({ page: 1, size: 1, status: 'draft' }),
      invoicesApi.list({ page: 1, size: 1, status: 'rejected' }),
    ])
      .then(([all, acc, ready, draft, rej]) => {
        if (cancelled) return;
        setStats({
          total:    all.total,
          accepted: acc.total,
          ready:    ready.total,
          draft:    draft.total,
          rejected: rej.total,
        });
      })
      .finally(() => { if (!cancelled) setStatsLoading(false); });
    return () => { cancelled = true; };
  }, []);

  // Dane wykresu — efektywny zakres + aktywne filtry
  const status     = filters?.status     || '';
  const contractor = filters?.contractor || '';

  useEffect(() => {
    let cancelled = false;
    setChart(prev => ({ ...prev, loading: true }));

    const baseParams = {
      size: 100, page: 1,
      issue_date_from: effectFrom,
      issue_date_to:   effectTo,
      ...(status     && { status }),
      ...(contractor && { number_filter: contractor }),
    };

    Promise.all([
      invoicesApi.list({ ...baseParams, direction: 'sale'     }),
      invoicesApi.list({ ...baseParams, direction: 'purchase' }),
    ])
      .then(([saleRes, purchaseRes]) => {
        if (cancelled) return;
        const sales     = saleRes.items     ?? [];
        const purchases = purchaseRes.items ?? [];

        // Jeden setState = jeden render, brak race-condition
        setChart({ loading: false, saleInvoices: sales, purchaseInvoices: purchases, currentRates: {} });

        // Kursy NBP dla walut obcych — osobna aktualizacja (niekrytyczna)
        const currencies = [...new Set(
          [...sales, ...purchases].map(i => i.currency).filter(c => c && c !== 'PLN'),
        )];
        if (currencies.length > 0) {
          Promise.all(currencies.map(c => fetchNbpRate(c).then(rate => [c, rate])))
            .then(pairs => {
              if (cancelled) return;
              setChart(prev => ({
                ...prev,
                currentRates: Object.fromEntries(pairs.filter(([, r]) => r !== null)),
              }));
            });
        }
      })
      .catch(() => {
        if (!cancelled)
          setChart({ loading: false, saleInvoices: [], purchaseInvoices: [], currentRates: {} });
      });
    return () => { cancelled = true; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [effectFrom, effectTo, status, contractor]);

  const combinedData = useMemo(() => {
    const saleMap     = buildDailyMap(chart.saleInvoices);
    const purchaseMap = buildDailyMap(chart.purchaseInvoices);
    return buildCombinedData(saleMap, purchaseMap);
  }, [chart.saleInvoices, chart.purchaseInvoices]);

  const lastSale     = combinedData.length ? combinedData[combinedData.length - 1].cumSale     : 0;
  const lastPurchase = combinedData.length ? combinedData[combinedData.length - 1].cumPurchase : 0;

  const saleForeignSummary = useMemo(() => buildForeignSummary(chart.saleInvoices), [chart.saleInvoices]);

  const fxDiff = useMemo(() => {
    let diff = 0;
    for (const [cur, { grossForeign, grossPln }] of Object.entries(saleForeignSummary)) {
      const curRate = chart.currentRates[cur];
      if (!curRate) continue;
      diff += grossForeign * curRate - grossPln;
    }
    return +diff.toFixed(2);
  }, [saleForeignSummary, chart.currentRates]);

  return (
    <div className={styles.root}>
      {/* ---- Wykres narastający sprzedaż vs zakupy ---- */}
      <div className={styles.chartWrap}>
        <div className={styles.chartHeader}>
          <h3 className={styles.chartTitle}>
            Sprzedaż i zakupy narastająco (brutto)
          </h3>
          <div className={styles.chartCorner}>
            <span className={styles.monthLabel}>wybrany okres: {periodLabel}</span>
            {optsLabel && (
              <span className={styles.wybranoLabel}>wybrane opcje: {optsLabel}</span>
            )}
          </div>
        </div>
        {chart.loading ? (
          <div className={styles.chartEmpty}><span className="spinner" /></div>
        ) : combinedData.length === 0 ? (
          <div className={styles.chartEmpty}>Brak faktur w wybranym okresie</div>
        ) : (
          <div className={styles.chartInner}>
            <ResponsiveContainer width="100%" height={250}>
              <AreaChart data={combinedData} margin={{ top: 8, right: 24, bottom: 0, left: 8 }}>
                <defs>
                  <linearGradient id="gradSale" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="#d4a017" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="#d4a017" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="gradPurchase" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="#3b82f6" stopOpacity={0.20} />
                    <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="#2e2e2e" strokeDasharray="4 4" vertical={false} />
                <XAxis
                  dataKey="date"
                  tick={{ fill: '#a0a0a0', fontSize: 12 }}
                  axisLine={{ stroke: '#2e2e2e' }}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fill: '#a0a0a0', fontSize: 12 }}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={(v) => v.toLocaleString('pl-PL')}
                  width={72}
                />
                <Tooltip
                  content={<CombinedTooltip />}
                  cursor={{ stroke: '#555', strokeWidth: 1, strokeDasharray: '4 4' }}
                />
                <Area
                  type="monotone"
                  dataKey="cumSale"
                  name="Sprzedaż"
                  stroke="#d4a017"
                  strokeWidth={2}
                  fill="url(#gradSale)"
                  dot={{ r: 4, fill: '#d4a017', strokeWidth: 0 }}
                  activeDot={{ r: 6, fill: '#e8b820', strokeWidth: 0 }}
                  isAnimationActive={false}
                />
                <Area
                  type="monotone"
                  dataKey="cumPurchase"
                  name="Zakupy"
                  stroke="#3b82f6"
                  strokeWidth={2}
                  fill="url(#gradPurchase)"
                  dot={{ r: 4, fill: '#3b82f6', strokeWidth: 0 }}
                  activeDot={{ r: 6, fill: '#60a5fa', strokeWidth: 0 }}
                  isAnimationActive={false}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
        {!chart.loading && combinedData.length > 0 && (
          <div className={styles.chartLegend}>
            <span className={styles.legendSale}>
              Sprzedaż: {lastSale.toLocaleString('pl-PL', { minimumFractionDigits: 2 })} PLN
              {Object.entries(saleForeignSummary).map(([cur, { grossForeign }]) => (
                <span key={cur} className={styles.legendForeign}>
                  {' + '}{grossForeign.toLocaleString('pl-PL', { minimumFractionDigits: 2 })} {cur}
                </span>
              ))}
            </span>
            <span className={styles.legendPurchase}>
              Zakupy: {lastPurchase.toLocaleString('pl-PL', { minimumFractionDigits: 2 })} PLN
            </span>
            {Object.keys(saleForeignSummary).length > 0 && Object.keys(chart.currentRates).length > 0 && (
              <span className={fxDiff >= 0 ? styles.legendFxGain : styles.legendFxLoss}>
                Różnica kursowa:{' '}
                {fxDiff >= 0 ? '+' : ''}
                {fxDiff.toLocaleString('pl-PL', { minimumFractionDigits: 2 })} PLN
              </span>
            )}
          </div>
        )}
      </div>

      {/* ---- Karty metryk ---- */}
      <div className={styles.grid}>
        {METRICS.map((m) => (
          <div key={m.key} className={`${styles.card} ${styles[m.cls]}`}>
            <span className={styles.value}>
              {statsLoading ? <span className="spinner" /> : stats[m.key]}
            </span>
            <span className={styles.label}>{m.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
