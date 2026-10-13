// Search: seeds a few indexed documents per VU, then runs full-text queries and suggestions.
// Requires search-service (not part of the 5-service core profile; perf.yml starts it).
import http from 'k6/http';
import { check, sleep } from 'k6';
import { BASE_URL, authHeaders, stages, thresholds, vuSession } from './lib/common.js';

export const options = {
  stages,
  thresholds: thresholds({ search_query: 500, search_suggest: 300 }),
};

const TERMS = ['otter', 'quarterly', 'roadmap', 'invoice', 'meeting'];
const seeded = {};

function seed(user, headers) {
  if (seeded[user.id]) return;
  const now = new Date().toISOString();
  TERMS.forEach((term, i) => {
    const res = http.post(
      `${BASE_URL}/api/v1/search/index/document`,
      JSON.stringify({
        id: `perf-${user.id}-${i}`,
        title: `${term} perf document`,
        content: `otterworks ${term} perf searchable content`,
        owner_id: user.id,
        type: 'document',
        created_at: now,
        updated_at: now,
      }),
      { headers, tags: { name: 'search_index' } },
    );
    check(res, { 'index 201': (r) => r.status === 201 });
  });
  seeded[user.id] = true;
  sleep(1); // let MeiliSearch apply the indexing task
}

export default function () {
  const user = vuSession('perf-search');
  const headers = authHeaders(user.token, { 'Content-Type': 'application/json' });
  seed(user, headers);

  const term = TERMS[__ITER % TERMS.length];
  const q = http.get(`${BASE_URL}/api/v1/search/?q=${term}&owner_id=${user.id}&page=1&size=10`, {
    headers,
    tags: { name: 'search_query' },
  });
  check(q, { 'search 200': (r) => r.status === 200 });

  const s = http.get(`${BASE_URL}/api/v1/search/suggest?q=${term.slice(0, 2)}`, {
    headers,
    tags: { name: 'search_suggest' },
  });
  check(s, { 'suggest 200': (r) => r.status === 200 });
  sleep(1);
}
