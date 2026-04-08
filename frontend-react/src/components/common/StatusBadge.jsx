import styles from './StatusBadge.module.css';

const STATUS_MAP = {
  // Invoice statuses
  draft:                 { label: 'Szkic',          cls: 'neutral' },
  ready_for_submission:  { label: 'Gotowa',          cls: 'info'    },
  sending:               { label: 'Wysyłanie',       cls: 'warning' },
  accepted:              { label: 'Zaakceptowana',   cls: 'success' },
  rejected:              { label: 'Odrzucona',       cls: 'error'   },
  // Transmission statuses
  queued:                { label: 'Kolejka',         cls: 'neutral' },
  submitted:             { label: 'Wysłana',         cls: 'info'    },
  waiting_status:        { label: 'Oczekuje',        cls: 'warning' },
  success:               { label: 'Sukces',          cls: 'success' },
  failed_permanent:      { label: 'Błąd stały',      cls: 'error'   },
  failed_retryable:      { label: 'Błąd (retry)',    cls: 'warning' },
  // Payment statuses
  unpaid:                { label: 'Nieopłacona',     cls: 'error'   },
  partially_paid:        { label: 'Częściowo',       cls: 'warning' },
  paid:                  { label: 'Opłacona',        cls: 'success' },
  // Generic
  active:                { label: 'Aktywna',         cls: 'success' },
  expired:               { label: 'Wygasła',         cls: 'neutral' },
};

export default function StatusBadge({ status }) {
  const entry = STATUS_MAP[status] ?? { label: status, cls: 'neutral' };
  return (
    <span className={`${styles.badge} ${styles[entry.cls]}`}>
      {entry.label}
    </span>
  );
}
