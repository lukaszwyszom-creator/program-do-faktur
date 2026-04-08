import client from './client';

export const contractorsApi = {
  getByNip: (nip) =>
    client.get(`/contractors/by-nip/${nip}`).then((r) => r.data),

  refresh: (nip) =>
    client.post(`/contractors/refresh/${nip}`).then((r) => r.data),

  createManual: (body) =>
    client.post('/contractors/', body).then((r) => r.data),
};
