import client from './client';

export const paymentsApi = {
  listTransactions: (params) =>
    client.get('/payments/transactions', { params }).then((r) => r.data),

  importCsv: (file) => {
    const form = new FormData();
    form.append('file', file);
    return client
      .post('/payments/import', form, { headers: { 'Content-Type': 'multipart/form-data' } })
      .then((r) => r.data);
  },

  rematch: (transactionId) =>
    client.post(`/payments/transactions/${transactionId}/match`).then((r) => r.data),

  allocate: (transactionId, body) =>
    client.post(`/payments/transactions/${transactionId}/allocate`, body).then((r) => r.data),

  reverseAllocation: (allocationId) =>
    client.delete(`/payments/allocations/${allocationId}`).then((r) => r.data),

  invoiceHistory: (invoiceId) =>
    client.get(`/payments/invoice/${invoiceId}/history`).then((r) => r.data),
};
