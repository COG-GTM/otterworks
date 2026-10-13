// Document CRUD: create, read, update, list and delete via /api/v1/documents.
import http from 'k6/http';
import { check, sleep } from 'k6';
import { BASE_URL, authHeaders, stages, thresholds, vuSession } from './lib/common.js';

export const options = {
  stages,
  thresholds: thresholds({
    doc_create: 800,
    doc_get: 300,
    doc_update: 800,
    doc_list: 500,
    doc_delete: 500,
  }),
};

export default function () {
  const user = vuSession('perf-doc');
  const headers = authHeaders(user.token, { 'Content-Type': 'application/json' });

  const created = http.post(
    `${BASE_URL}/api/v1/documents/`,
    JSON.stringify({ title: `perf doc ${__VU}-${__ITER}`, content: 'hello perf world' }),
    { headers, tags: { name: 'doc_create' } },
  );
  if (!check(created, { 'create 201': (r) => r.status === 201 })) return;
  const id = created.json('id');

  check(http.get(`${BASE_URL}/api/v1/documents/${id}`, { headers, tags: { name: 'doc_get' } }), {
    'get 200': (r) => r.status === 200,
  });
  check(
    http.put(
      `${BASE_URL}/api/v1/documents/${id}`,
      JSON.stringify({ title: `perf doc ${__VU}-${__ITER} v2`, content: 'updated perf body text' }),
      { headers, tags: { name: 'doc_update' } },
    ),
    { 'update 200': (r) => r.status === 200 },
  );
  check(
    http.get(`${BASE_URL}/api/v1/documents/?owner_id=${user.id}&page=1&size=10`, {
      headers,
      tags: { name: 'doc_list' },
    }),
    { 'list 200': (r) => r.status === 200 },
  );
  check(http.del(`${BASE_URL}/api/v1/documents/${id}`, null, { headers, tags: { name: 'doc_delete' } }), {
    'delete 2xx': (r) => r.status === 204 || r.status === 200,
  });
  sleep(1);
}
