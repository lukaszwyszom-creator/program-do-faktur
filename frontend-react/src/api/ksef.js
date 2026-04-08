import client from './client';

export const ksefApi = {
  openSession: (nip) =>
    client.post('/ksef-sessions/', { nip }).then((r) => r.data),

  getActiveSession: (nip) =>
    client.get('/ksef-sessions/active', { params: { nip } }).then((r) => r.data),

  closeSession: (sessionId) =>
    client.post(`/ksef-sessions/${sessionId}/close`).then((r) => r.data),
};
