import styles from './Pagination.module.css';

/**
 * @param {number} page
 * @param {number} total
 * @param {number} size
 * @param {Function} onPage (page) => void
 */
export default function Pagination({ page, total, size, onPage }) {
  const totalPages = Math.ceil(total / size);
  if (totalPages <= 1) return null;

  const from = (page - 1) * size + 1;
  const to = Math.min(page * size, total);

  return (
    <div className={styles.bar}>
      <span className={styles.info}>
        {from}–{to} z {total}
      </span>
      <div className={styles.btns}>
        <button
          className="btn btn-ghost btn-sm"
          disabled={page <= 1}
          onClick={() => onPage(page - 1)}
        >
          ‹ Poprzednia
        </button>
        <span className={styles.current}>{page} / {totalPages}</span>
        <button
          className="btn btn-ghost btn-sm"
          disabled={page >= totalPages}
          onClick={() => onPage(page + 1)}
        >
          Następna ›
        </button>
      </div>
    </div>
  );
}
