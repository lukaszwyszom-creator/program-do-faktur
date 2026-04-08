import client from './client';

export const invoicesApi = {
  list: (params) =>
    client.get('/invoices/', { params }).then((r) => r.data),

  get: (id) =>
    client.get(`/invoices/${id}`).then((r) => r.data),

  create: (body, idempotencyKey) =>
    client
      .post('/invoices/', body, {
        headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : {},
      })
      .then((r) => r.data),

  markReady: (id) =>
    client.post(`/invoices/${id}/mark-ready`).then((r) => r.data),

  /** Zwraca HTML podglądu jako string (text/html). */
  getPreview: (id) =>
    client.get(`/invoices/${id}/preview`, { responseType: 'text' }).then((r) => r.data),

  /** Zwraca binarne bajty PDF (application/pdf). */
  getPdf: (id) =>
    client.get(`/invoices/${id}/pdf`, { responseType: 'arraybuffer' }).then((r) => r.data),
};
