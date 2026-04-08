import client from './client';

export const transmissionsApi = {
  list: (page = 1, size = 20) =>
    client.get('/transmissions/', { params: { page, size } }).then((r) => r.data),

  submit: (invoiceId) =>
    client.post(`/transmissions/submit/${invoiceId}`).then((r) => r.data),

  get: (transmissionId) =>
    client.get(`/transmissions/${transmissionId}`).then((r) => r.data),

  retry: (transmissionId) =>
    client.post(`/transmissions/${transmissionId}/retry`).then((r) => r.data),

  getKsefStatus: (transmissionId) =>
    client.get(`/transmissions/${transmissionId}/ksef-status`).then((r) => r.data),
};
