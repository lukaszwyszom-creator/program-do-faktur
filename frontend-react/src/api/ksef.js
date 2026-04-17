import client from './client';

export const ksefApi = {
  openSession: (nip) =>
    client.post('/ksef-sessions/', { nip }).then((r) => r.data),

  getActiveSession: (nip) =>
    client.get('/ksef-sessions/active', { params: { nip } }).then((r) => r.data),

  closeSession: (nip) =>
    client.delete('/ksef-sessions/', { params: { nip } }).then((r) => r.data),

  syncPurchaseInvoices: (nip, dateFrom, dateTo) =>
    client
      .post('/ksef-sessions/sync-purchase', { nip, date_from: dateFrom, date_to: dateTo })
      .then((r) => r.data),
};
