import client from './client';

export const settingsApi = {
  get: () =>
    client.get('/settings/').then((r) => r.data),

  update: (data) =>
    client.put('/settings/', data).then((r) => r.data),
};
