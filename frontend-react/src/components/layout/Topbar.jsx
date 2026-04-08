import { useLocation, useNavigate } from 'react-router-dom';
import { useAppStore } from '../../store/useAppStore';
import { useAuthStore } from '../../store/useAuthStore';
import styles from './Topbar.module.css';

const PAGE_TITLES = {
  '/simple':   'Faktury — tryb prosty',
  '/advanced': 'Dashboard — tryb rozszerzony',
  '/payments': 'Płatności — import i rozliczenie',
};

export default function Topbar() {
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
        <span className={styles.pageTitle}>
          {PAGE_TITLES[location.pathname] ?? 'System Fakturowania'}
        </span>
      </div>

      <div className={styles.right}>
        <button className={`btn btn-secondary btn-sm ${styles.modeToggle}`} onClick={toggleMode}>
          <span className={styles.modeDot} data-mode={mode} />
          {mode === 'simple' ? 'Przełącz na ADVANCED' : 'Przełącz na SIMPLE'}
        </button>

        <div className={styles.userBadge}>
          <span className={styles.userIcon}>👤</span>
          <span className={styles.userName}>{user?.username ?? 'operator'}</span>
        </div>
      </div>
    </header>
  );
}
