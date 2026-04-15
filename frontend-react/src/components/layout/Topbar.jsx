import { useLocation, useNavigate } from 'react-router-dom';
import { useAppStore } from '../../store/useAppStore';
import { useAuthStore } from '../../store/useAuthStore';
import styles from './Topbar.module.css';

const PAGE_TITLES = {
  '/simple':   'Faktury',
  '/advanced': 'Dashboard',
  '/payments': 'Płatności',
  '/stock':    'Magazyn',
};

export default function Topbar({ onMenuToggle }) {
  const location = useLocation();
  const navigate = useNavigate();
  const mode = useAppStore((s) => s.mode);
  const setMode = useAppStore((s) => s.setMode);
  const user = useAuthStore((s) => s.user);

  const toggleMode = () => {
    const next = mode === 'simple' ? 'advanced' : 'simple';
    setMode(next);
    navigate(`/${next}`);
  };

  return (
    <header className={styles.topbar}>
      <div className={styles.left}>
        <button className={styles.menuBtn} onClick={onMenuToggle} aria-label="Menu">
          ☰
        </button>
        <span className={styles.pageTitle}>
          {PAGE_TITLES[location.pathname] ?? 'System Fakturowania'}
        </span>
      </div>

      <div className={styles.right}>
        <button className={`btn btn-secondary btn-sm ${styles.modeToggle}`} onClick={toggleMode}>
          <span className={styles.modeDot} data-mode={mode} />
          <span className={styles.modeLabel}>
            {mode === 'simple' ? 'ADVANCED' : 'SIMPLE'}
          </span>
        </button>

        <div className={styles.userBadge}>
          <span className={styles.userIcon}>👤</span>
          <span className={styles.userName}>{user?.username ?? 'operator'}</span>
        </div>
      </div>
    </header>
  );
}
