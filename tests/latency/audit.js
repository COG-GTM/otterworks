// audit-service (.NET), hit directly on its own port. setup() seeds SEED_EVENTS
// events so the read paths have data to return.
import http from 'k6/http';
import { buildScenarios, registerEndpoints, record, jsonParams, summarize } from './lib/common.js';

const BASE = __ENV.AUDIT_URL || 'http://localhost:8090';
const SEED_EVENTS = Number(__ENV.SEED_EVENTS || 500);
const ENDPOINTS = [
  'audit_record_event',
  'audit_query_events',
  'audit_get_event',
  'audit_resource_history',
  'audit_user_report',
];
registerEndpoints(ENDPOINTS);

export const options = {
  scenarios: buildScenarios(ENDPOINTS),
  summaryTrendStats: ['p(50)', 'p(95)', 'p(99)', 'count'],
  setupTimeout: '300s',
};

function event(userId, resourceId, i) {
  return JSON.stringify({
    userId,
    action: ['file.view', 'file.edit', 'document.share', 'auth.login'][i % 4],
    resourceType: 'file',
    resourceId,
    details: { source: 'latency-test', seq: String(i) },
    ipAddress: '10.0.0.1',
    userAgent: 'k6',
  });
}

export function setup() {
  const runId = `${Date.now()}`;
  const userId = `latency-user-${runId}`;
  const resourceId = `latency-resource-${runId}`;
  let eventId = null;
  const batch = [];
  for (let i = 0; i < SEED_EVENTS; i++) {
    batch.push(['POST', `${BASE}/api/v1/audit/events`, event(userId, `${resourceId}-${i % 10}`, i), jsonParams()]);
    if (batch.length === 50 || i === SEED_EVENTS - 1) {
      for (const res of http.batch(batch.splice(0))) {
        if (res.status !== 201) throw new Error(`seed failed: ${res.status} ${res.body}`);
        eventId = res.json().id;
      }
    }
  }
  return { userId, resourceId: `${resourceId}-0`, eventId };
}

export function run(seed) {
  const name = __ENV.ENDPOINT;
  if (name === 'audit_record_event') {
    const res = http.post(`${BASE}/api/v1/audit/events`, event(seed.userId, seed.resourceId, __ITER), jsonParams());
    record(name, res, 201);
  } else if (name === 'audit_query_events') {
    record(name, http.get(`${BASE}/api/v1/audit/events?user_id=${seed.userId}&page=1&size=20`), 200);
  } else if (name === 'audit_get_event') {
    record(name, http.get(`${BASE}/api/v1/audit/events/${seed.eventId}`), 200);
  } else if (name === 'audit_resource_history') {
    record(name, http.get(`${BASE}/api/v1/audit/resources/${seed.resourceId}/history`), 200);
  } else if (name === 'audit_user_report') {
    record(name, http.get(`${BASE}/api/v1/audit/reports/user/${seed.userId}?period=30d`), 200);
  }
}

export const handleSummary = summarize('audit-service', ENDPOINTS);
