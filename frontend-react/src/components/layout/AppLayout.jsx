import { useState } from 'react';
import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import Topbar from './Topbar';
import styles from './AppLayout.module.css';

export default function AppLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <div className={styles.shell}>
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      {sidebarOpen && (
        <div className={styles.overlay} onClick={() => setSidebarOpen(false)} />
      )}
      <div className={styles.main}>
        <Topbar onMenuToggle={() => setSidebarOpen((v) => !v)} />
        <main className={styles.content}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
