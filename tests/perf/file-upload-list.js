// File upload + list: multipart POST /api/v1/files/upload (S3 + DynamoDB), then GET /api/v1/files.
import http from 'k6/http';
import { check, sleep } from 'k6';
import { BASE_URL, authHeaders, stages, thresholds, vuSession } from './lib/common.js';

export const options = {
  stages,
  thresholds: thresholds({ file_upload: 1500, file_list: 500, file_delete: 800 }),
};

const PAYLOAD = 'x'.repeat(Number(__ENV.FILE_BYTES || 16 * 1024));

export default function () {
  const user = vuSession('perf-file');
  const upload = http.post(
    `${BASE_URL}/api/v1/files/upload`,
    { file: http.file(PAYLOAD, `perf-${__VU}-${__ITER}.txt`, 'text/plain') },
    { headers: authHeaders(user.token), tags: { name: 'file_upload' } },
  );
  check(upload, { 'upload 201': (r) => r.status === 201 });

  const list = http.get(`${BASE_URL}/api/v1/files?page=1&page_size=20`, {
    headers: authHeaders(user.token),
    tags: { name: 'file_list' },
  });
  check(list, {
    'list 200': (r) => r.status === 200,
    'list has files': (r) => (r.json('files') || []).length > 0,
  });

  // Keep the per-user listing bounded across long runs.
  const fileId = upload.status === 201 ? upload.json('file.id') : null;
  if (fileId) {
    const del = http.del(`${BASE_URL}/api/v1/files/${fileId}`, null, {
      headers: authHeaders(user.token),
      tags: { name: 'file_delete' },
    });
    check(del, { 'delete 204': (r) => r.status === 204 });
  }
  sleep(1);
}
