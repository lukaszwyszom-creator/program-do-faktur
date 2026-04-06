/**
 * app.js — wspólne narzędzia: autoryzacja, klient API, UI helpers
 *
 * Ładowany przez każdą stronę jako <script src="/ui/static/app.js"></script>
 */

/* ================== AUTH ================== */

const TOKEN_KEY = "faktury_token";

export function getToken() {
  return sessionStorage.getItem(TOKEN_KEY) || localStorage.getItem(TOKEN_KEY);
}

export function saveToken(token, persist = true) {
  sessionStorage.setItem(TOKEN_KEY, token);
  if (persist) localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  sessionStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(TOKEN_KEY);
}

export function requireAuth() {
  if (!getToken()) {
    window.location.href = "/ui/login";
  }
}

/* ================== API CLIENT ================== */

const API_BASE = "/api/v1";

async function apiFetch(path, options = {}) {
  const token = getToken();
  const headers = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {}),
  };
  const res = await fetch(API_BASE + path, { ...options, headers });

  if (res.status === 401) {
    clearToken();
    window.location.href = "/ui/login";
    return null;
  }

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch (_) {}
    throw new Error(detail);
  }

  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  /* Auth */
  login: (username, password) =>
    apiFetch("/auth/token", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),

  /* Invoices */
  listInvoices: (params = {}) => {
    const qs = new URLSearchParams(
      Object.fromEntries(Object.entries(params).filter(([, v]) => v !== null && v !== "" && v !== undefined))
    ).toString();
    return apiFetch(`/invoices/${qs ? "?" + qs : ""}`);
  },

  getInvoice: (id) => apiFetch(`/invoices/${id}`),

  markReady: (id) => apiFetch(`/invoices/${id}/mark-ready`, { method: "POST" }),

  pdfUrl: (id) => `${API_BASE}/invoices/${id}/pdf`,

  /* Transmissions */
  submitInvoice: (invoiceId) =>
    apiFetch(`/transmissions/submit/${invoiceId}`, { method: "POST" }),

  retryTransmission: (transmissionId) =>
    apiFetch(`/transmissions/${transmissionId}/retry`, { method: "POST" }),

  listTransmissions: (invoiceId) =>
    apiFetch(`/transmissions/invoice/${invoiceId}`),

  getKSeFStatus: (transmissionId) =>
    apiFetch(`/transmissions/${transmissionId}/ksef-status`),

  upoUrl: (transmissionId) => `${API_BASE}/transmissions/${transmissionId}/upo`,

  /* Payments */
  importPaymentsCsv: (formData) => {
    const token = getToken();
    return fetch(API_BASE + "/payments/import", {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      body: formData,
    }).then(async (res) => {
      if (res.status === 401) { clearToken(); window.location.href = "/ui/login"; return null; }
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try { const b = await res.json(); detail = b.detail || detail; } catch (_) {}
        throw new Error(detail);
      }
      return res.json();
    });
  },

  listTransactions: (params = {}) => {
    const qs = new URLSearchParams(
      Object.fromEntries(Object.entries(params).filter(([, v]) => v !== null && v !== "" && v !== undefined))
    ).toString();
    return apiFetch(`/payments/transactions${qs ? "?" + qs : ""}`);
  },

  rematchTransaction: (txId) =>
    apiFetch(`/payments/transactions/${txId}/match`, { method: "POST" }),

  allocateManual: (txId, invoiceId, amount) =>
    apiFetch(`/payments/transactions/${txId}/allocate`, {
      method: "POST",
      body: JSON.stringify({ invoice_id: invoiceId, amount }),
    }),

  reverseAllocation: (allocId) =>
    apiFetch(`/payments/allocations/${allocId}`, { method: "DELETE" }),

  getInvoicePaymentHistory: (invoiceId) =>
    apiFetch(`/payments/invoice/${invoiceId}/history`),
};

/* ================== UI HELPERS ================== */

const STATUS_LABELS = {
  // Invoice KSeF status
  draft: "Szkic",
  ready_for_submission: "Gotowa do wysyłki",
  sending: "Wysyłanie",
  accepted: "Zatwierdzona",
  rejected: "Odrzucona",
  // Transmission status
  queued: "W kolejce",
  processing: "Przetwarzanie",
  submitted: "Zgłoszona",
  waiting_status: "Oczekiwanie",
  success: "Sukces",
  failed_retryable: "Błąd (ponów)",
  failed_permanent: "Błąd trwały",
  // Payment status
  unpaid: "Nieopłacona",
  partially_paid: "Częściowo opłacona",
  paid: "Opłacona",
  // Match status
  unmatched: "Bez dopasowania",
  matched: "Dopasowana",
  partial: "Częściowe",
  manual_review: "Do przeglądu",
};

export function statusLabel(status) {
  return STATUS_LABELS[status] ?? status;
}

export function badgeHtml(status) {
  return `<span class="badge badge-${escHtml(status)}">${escHtml(statusLabel(status))}</span>`;
}

export function escHtml(str) {
  if (str == null) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function formatMoney(amount, currency = "PLN") {
  const n = parseFloat(amount);
  if (isNaN(n)) return amount;
  return (
    n.toLocaleString("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) +
    " " +
    currency
  );
}

/* -- Toast notifications -- */

let _toastContainer = null;
function _getToastContainer() {
  if (!_toastContainer) {
    _toastContainer = document.createElement("div");
    _toastContainer.className = "toast-container";
    document.body.appendChild(_toastContainer);
  }
  return _toastContainer;
}

export function showToast(message, type = "", duration = 3500) {
  const container = _getToastContainer();
  const el = document.createElement("div");
  el.className = `toast${type ? " " + type : ""}`;
  el.textContent = message;
  container.appendChild(el);
  requestAnimationFrame(() => el.classList.add("show"));
  setTimeout(() => {
    el.classList.remove("show");
    setTimeout(() => el.remove(), 250);
  }, duration);
}

/* -- Loading state -- */

export function setLoading(container, message = "Ładowanie…") {
  container.innerHTML = `<div class="state-loading">${escHtml(message)}</div>`;
}

export function setError(container, message) {
  container.innerHTML = `<div class="state-error">⚠ ${escHtml(message)}</div>`;
}

/* -- PWA service worker registration -- */

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker
      .register("/ui/sw.js")
      .catch(() => {/* silent — not critical */});
  });
}
