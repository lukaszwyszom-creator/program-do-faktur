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

function buildDailyMap(invoices, prefix) {
  const map = {};
  for (const inv of invoices) {
    const d = (inv.issue_date ?? '').toString().slice(0, 10);
    if (!d.startsWith(prefix)) continue;
    map[d] = (map[d] ?? 0) + Number(inv.total_gross ?? 0);
  }
  return map;
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

export default function DashboardSummary({ filters }) {
  const [stats, setStats]               = useState({ total: 0, accepted: 0, ready: 0, draft: 0, rejected: 0 });
  const [statsLoading, setStatsLoading] = useState(false);
  const [allSale, setAllSale]           = useState([]);
  const [allPurchase, setAllPurchase]   = useState([]);
  const [chartLoading, setChartLoading] = useState(true);

  // Karty metryk
  useEffect(() => {
    setStatsLoading(true);
    Promise.all([
      invoicesApi.list({ page: 1, size: 1 }),
      invoicesApi.list({ page: 1, size: 1, status: 'accepted' }),
      invoicesApi.list({ page: 1, size: 1, status: 'ready_for_submission' }),
      invoicesApi.list({ page: 1, size: 1, status: 'draft' }),
      invoicesApi.list({ page: 1, size: 1, status: 'rejected' }),
    ])
      .then(([all, acc, ready, draft, rej]) => {
        setStats({
          total:    all.total,
          accepted: acc.total,
          ready:    ready.total,
          draft:    draft.total,
          rejected: rej.total,
        });
      })
      .finally(() => setStatsLoading(false));
  }, [filters]);

  // Dane wykresu — sprzedaż i zakupy równolegle
  useEffect(() => {
    setChartLoading(true);
    Promise.all([
      invoicesApi.list({ direction: 'sale',     size: 100, page: 1 }),
      invoicesApi.list({ direction: 'purchase', size: 100, page: 1 }),
    ])
      .then(([saleRes, purchaseRes]) => {
        setAllSale(saleRes.items ?? []);
        setAllPurchase(purchaseRes.items ?? []);
      })
      .catch(() => { setAllSale([]); setAllPurchase([]); })
      .finally(() => setChartLoading(false));
  }, [filters]);

  const prefix = useMemo(() => currentMonthPrefix(), []);

  const combinedData = useMemo(() => {
    const saleMap     = buildDailyMap(allSale,     prefix);
    const purchaseMap = buildDailyMap(allPurchase, prefix);
    return buildCombinedData(saleMap, purchaseMap);
  }, [allSale, allPurchase, prefix]);

  const lastSale     = combinedData.length ? combinedData[combinedData.length - 1].cumSale     : 0;
  const lastPurchase = combinedData.length ? combinedData[combinedData.length - 1].cumPurchase : 0;

  return (
    <div className={styles.root}>
      {/* ---- Wykres narastający sprzedaż vs zakupy ---- */}
      <div className={styles.chartWrap}>
        <h3 className={styles.chartTitle}>
          Sprzedaż i zakupy narastająco w miesiącu (brutto)
        </h3>
        {chartLoading ? (
          <div className={styles.chartEmpty}><span className="spinner" /></div>
        ) : combinedData.length === 0 ? (
          <div className={styles.chartEmpty}>Brak faktur w bieżącym miesiącu ({prefix})</div>
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
        {!chartLoading && combinedData.length > 0 && (
          <div className={styles.chartLegend}>
            <span className={styles.legendSale}>
              Sprzedaż: {lastSale.toLocaleString('pl-PL', { minimumFractionDigits: 2 })} PLN
            </span>
            <span className={styles.legendPurchase}>
              Zakupy: {lastPurchase.toLocaleString('pl-PL', { minimumFractionDigits: 2 })} PLN
            </span>
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
