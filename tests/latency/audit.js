// audit-service (.NET, :8090): record event (write), query a user's events (read).
// setup() tops the audit table up to SEED_EVENTS rows so the read path runs
// against a table of known minimum size.
import http from 'k6/http';
import { check, fail } from 'k6';
import { buildOptions, makeSummary, runId } from './lib/latency.js';

const BASE = __ENV.AUDIT_URL || 'http://localhost:8090';
const SEED_EVENTS = parseInt(__ENV.SEED_EVENTS || '2000', 10);
const JSON_HDR = { headers: { 'Content-Type': 'application/json' } };
const ACTIONS = ['file.upload', 'file.download', 'document.edit', 'document.share', 'auth.login'];

export const options = buildOptions(['audit_record_event', 'audit_query_events']);

function event(userId, i) {
  return {
    userId,
    action: ACTIONS[i % ACTIONS.length],
    resourceType: i % 2 ? 'file' : 'document',
    resourceId: `res-${i % 200}`,
    details: { source: 'latency-check' },
  };
}

export function setup() {
  const id = runId();
  const before = http.get(`${BASE}/api/v1/audit/events?size=1`);
  if (before.status !== 200) fail(`audit query failed: ${before.status} ${before.body}`);
  let total = before.json('total');
  const users = Array.from({ length: 50 }, (_, i) => `latency-user-${i}`);
  while (total < SEED_EVENTS) {
    const batch = [];
    for (let i = 0; i < 50 && total + i < SEED_EVENTS; i++) {
      batch.push(['POST', `${BASE}/api/v1/audit/events`, JSON.stringify(event(users[(total + i) % users.length], total + i)), JSON_HDR]);
    }
    http.batch(batch);
    total += batch.length;
  }
  const after = http.get(`${BASE}/api/v1/audit/events?size=1`).json('total');
  console.log(`audit table holds ${after} events before load`);
  return { id, users };
}

export function audit_record_event(d) {
  const r = http.post(`${BASE}/api/v1/audit/events`, JSON.stringify(event(`latency-load-${d.id}`, __ITER)), JSON_HDR);
  check(r, { 'record 201': (res) => res.status === 201 });
}

export function audit_query_events(d) {
  const user = d.users[__ITER % d.users.length];
  const r = http.get(`${BASE}/api/v1/audit/events?user_id=${user}&page=1&size=20`);
  check(r, { 'query 200': (res) => res.status === 200 });
}

export const handleSummary = makeSummary('audit-service');
