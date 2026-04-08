import { useState, useEffect, useCallback } from 'react';
import { ksefApi } from '../../api/ksef';
import { settingsApi } from '../../api/settings';
import { useAppStore } from '../../store/useAppStore';
import styles from './KSeFSessionBar.module.css';

/**
 * Pasek statusu sesji KSeF wyświetlany w AdvancedDashboard.
 * Pozwala otworzyć, sprawdzić i zamknąć sesję KSeF dla podanego NIP.
 */
export default function KSeFSessionBar() {
  const storedNip = useAppStore((s) => s.sellerNip);
  const setSellerNip = useAppStore((s) => s.setSellerNip);

  const [nip, setNip] = useState(storedNip);
  const [session, setSession] = useState(null);  // KSeFSessionResponse | null
  const [busy, setBusy] = useState(false);
  const [checkLoading, setCheckLoading] = useState(false);
  const [error, setError] = useState('');
  const [successMsg, setSuccessMsg] = useState('');

  const clearMsgs = () => { setError(''); setSuccessMsg(''); };

  const checkSession = useCallback(async (nipToCheck) => {
    if (!nipToCheck || nipToCheck.length !== 10) return;
    setCheckLoading(true);
    clearMsgs();
    try {
      const s = await ksefApi.getActiveSession(nipToCheck);
      setSession(s);
    } catch (err) {
      if (err.response?.status === 404) {
        setSession(null); // brak aktywnej — to normalny stan
      } else {
        setError('Błąd sprawdzania sesji KSeF');
      }
    } finally {
      setCheckLoading(false);
    }
  }, []);

  // Przy zmianie NIP z store sprawdź automatycznie
  useEffect(() => {
    if (storedNip?.length === 10) {
      setNip(storedNip);
      checkSession(storedNip);
    }
  }, [storedNip, checkSession]);

  // Pobierz NIP z backendu jeśli store jest pusty
  useEffect(() => {
    if (!storedNip) {
      settingsApi.get()
        .then((s) => {
          if (s.seller_nip?.length === 10) {
            setSellerNip(s.seller_nip);
          }
        })
        .catch(() => { /* ignoruj — użytkownik wpisze ręcznie */ });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleNipChange = (val) => {
    setNip(val.replace(/\D/g, '').slice(0, 10));
  };

  const handleCheck = () => {
    setSellerNip(nip);
    checkSession(nip);
  };

  const handleOpen = async () => {
    clearMsgs();
    setBusy(true);
    try {
      const s = await ksefApi.openSession(nip);
      setSession(s);
      setSellerNip(nip);
      setSuccessMsg('Sesja KSeF otwarta pomyślnie');
    } catch (err) {
      const msg =
        err.response?.data?.error?.message ??
        err.response?.data?.detail ??
        'Błąd otwierania sesji';
      setError(msg);
    } finally {
      setBusy(false);
    }
  };

  const handleClose = async () => {
    if (!session) return;
    clearMsgs();
    setBusy(true);
    try {
      await ksefApi.closeSession(session.id);
      setSession(null);
      setSuccessMsg('Sesja KSeF zamknięta');
    } catch (err) {
      const msg =
        err.response?.data?.error?.message ??
        err.response?.data?.detail ??
        'Błąd zamykania sesji';
      setError(msg);
    } finally {
      setBusy(false);
    }
  };

  const isActive = session?.status === 'active';
  const nipValid = nip.length === 10;

  return (
    <div className={styles.bar}>
      <div className={styles.left}>
        <span className={styles.label}>Sesja KSeF</span>

        {isActive ? (
          <span className={styles.sessionInfo}>
            <span className={styles.dot} />
            Aktywna · NIP {session.nip}
            {session.session_reference && (
              <span className={styles.ref} title={session.session_reference}>
                · ref: {session.session_reference.slice(0, 12)}…
              </span>
            )}
          </span>
        ) : (
          <span className={styles.noSession}>Brak aktywnej sesji</span>
        )}
      </div>

      <div className={styles.right}>
        {!isActive && (
          <>
            <input
              className={`input ${styles.nipInput}`}
              type="text"
              placeholder="NIP sprzedawcy"
              maxLength={10}
              value={nip}
              onChange={(e) => handleNipChange(e.target.value)}
            />
            <button
              className="btn btn-ghost btn-sm"
              disabled={!nipValid || checkLoading}
              onClick={handleCheck}
            >
              {checkLoading ? <span className="spinner" style={{ width: 12, height: 12 }} /> : 'Sprawdź'}
            </button>
            <button
              className="btn btn-primary btn-sm"
              disabled={!nipValid || busy}
              onClick={handleOpen}
            >
              {busy ? <span className="spinner" style={{ width: 12, height: 12 }} /> : 'Otwórz sesję'}
            </button>
          </>
        )}

        {isActive && (
          <button
            className="btn btn-danger btn-sm"
            disabled={busy}
            onClick={handleClose}
          >
            {busy ? <span className="spinner" style={{ width: 12, height: 12 }} /> : 'Zamknij sesję'}
          </button>
        )}
      </div>

      {error      && <div className={styles.alertRow}><div className="alert alert-error">{error}</div></div>}
      {successMsg && <div className={styles.alertRow}><div className="alert alert-success">{successMsg}</div></div>}
    </div>
  );
}
