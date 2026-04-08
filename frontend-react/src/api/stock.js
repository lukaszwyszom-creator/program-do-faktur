import client from './client';

export const stockApi = {
  listStock: (warehouseId) =>
    client.get('/stock/', { params: warehouseId ? { warehouse_id: warehouseId } : {} }).then((r) => r.data),

  listMovements: (params) =>
    client.get('/stock/history', { params }).then((r) => r.data),

  listProducts: () =>
    client.get('/stock/products').then((r) => r.data),

  createProduct: (body) =>
    client.post('/stock/products', body).then((r) => r.data),

  createMovement: (body) =>
    client.post('/stock/movement', body).then((r) => r.data),
};
