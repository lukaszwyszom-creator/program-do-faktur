import { NavLink, useNavigate } from 'react-router-dom';
import { useAppStore } from '../../store/useAppStore';
import { useAuthStore } from '../../store/useAuthStore';
import styles from './Sidebar.module.css';
import logo from '../../assets/logo-ifg.png';

const NAV_ITEMS_SIMPLE   = [
  { to: '/simple',   label: 'Faktury',   icon: '📄' },
];
const NAV_ITEMS_ADVANCED = [
  { to: '/simple',   label: 'Faktury',   icon: '📄' },
  { to: '/advanced', label: 'Dashboard', icon: '📊' },
  { to: '/payments', label: 'Płatności', icon: '💳' },
];

export default function Sidebar() {
  const mode = useAppStore((s) => s.mode);
  const setMode = useAppStore((s) => s.setMode);
  const logout = useAuthStore((s) => s.logout);
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <aside className={styles.sidebar}>
      <div className={styles.logo}>
        <img src={logo} alt="IFG" className={styles.logoImg} />
        <span className={styles.logoText}>Imperium Faktur G</span>
      </div>

      <div className={styles.modeToggle}>
        <button
          className={`${styles.modeBtn} ${mode === 'simple' ? styles.active : ''}`}
          onClick={() => { setMode('simple'); navigate('/simple'); }}
        >
          SIMPLE
        </button>
        <button
          className={`${styles.modeBtn} ${mode === 'advanced' ? styles.active : ''}`}
          onClick={() => { setMode('advanced'); navigate('/advanced'); }}
        >
          ADVANCED
        </button>
      </div>

      <nav className={styles.nav}>
        {(mode === 'simple' ? NAV_ITEMS_SIMPLE : NAV_ITEMS_ADVANCED).map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `${styles.navItem} ${isActive ? styles.navActive : ''}`
            }
          >
            <span className={styles.navIcon}>{item.icon}</span>
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>

      <div className={styles.bottom}>
        <button className={styles.logoutBtn} onClick={handleLogout}>
          <span>↩</span> Wyloguj
        </button>
      </div>
    </aside>
  );
}
