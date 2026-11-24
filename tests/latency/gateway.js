// api-gateway (Go, :8080): its own health route, plus the auth read path and
// the audit write path proxied through it (JWT validation + reverse proxy).
import http from 'k6/http';
import { check, fail } from 'k6';
import { buildOptions, makeSummary, runId } from './lib/latency.js';

const BASE = __ENV.GATEWAY_URL || 'http://localhost:8080';
const JSON_HDR = { 'Content-Type': 'application/json' };

export const options = buildOptions(['gateway_health', 'gateway_profile', 'gateway_audit_record']);

export function setup() {
  const id = runId();
  const email = `latency-gw-${id}@otterworks.test`;
  const password = 'LatencyCheck-2026!';
  const reg = http.post(`${BASE}/api/v1/auth/register`, JSON.stringify({ email, password, displayName: 'Latency Gateway' }), { headers: JSON_HDR });
  if (reg.status !== 201 && reg.status !== 200) fail(`register via gateway failed: ${reg.status} ${reg.body}`);
  const token = reg.json('accessToken');
  const auth = { headers: Object.assign({ Authorization: `Bearer ${token}` }, JSON_HDR) };
  for (let i = 0; i < 20; i++) {
    http.get(`${BASE}/health`);
    http.get(`${BASE}/api/v1/auth/profile`, auth);
  }
  return { id, token };
}

const authed = (d) => ({ headers: Object.assign({ Authorization: `Bearer ${d.token}` }, JSON_HDR) });

export function gateway_health() {
  const r = http.get(`${BASE}/health`);
  check(r, { 'health 200': (res) => res.status === 200 });
}

export function gateway_profile(d) {
  const r = http.get(`${BASE}/api/v1/auth/profile`, authed(d));
  check(r, { 'profile 200': (res) => res.status === 200 });
}

export function gateway_audit_record(d) {
  const body = { userId: `latency-gw-${d.id}`, action: 'document.edit', resourceType: 'document', resourceId: `res-${__ITER % 200}` };
  const r = http.post(`${BASE}/api/v1/audit/events`, JSON.stringify(body), authed(d));
  check(r, { 'record 201': (res) => res.status === 201 });
}

export const handleSummary = makeSummary('api-gateway');
