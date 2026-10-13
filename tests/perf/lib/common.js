// Shared helpers for the OtterWorks k6 scripts.
import http from 'k6/http';
import { check, fail } from 'k6';

export const BASE_URL = __ENV.BASE_URL || 'http://localhost:8080';
export const PASSWORD = 'OtterworksPerf123!';

export const JSON_HEADERS = { 'Content-Type': 'application/json' };

export function authHeaders(token, extra = {}) {
  return Object.assign({ Authorization: `Bearer ${token}` }, extra);
}

export function uniqueEmail(prefix) {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1e9)}@perf.otterworks.test`;
}

// Registers a fresh user and returns { email, password, id, token }.
export function registerUser(prefix = 'perf') {
  const email = uniqueEmail(prefix);
  const res = http.post(
    `${BASE_URL}/api/v1/auth/register`,
    JSON.stringify({ email, password: PASSWORD, displayName: `${prefix} user` }),
    { headers: JSON_HEADERS, tags: { name: 'auth_register' } },
  );
  if (!check(res, { 'register 201': (r) => r.status === 201 })) {
    fail(`register failed: ${res.status} ${res.body}`);
  }
  const body = res.json();
  return { email, password: PASSWORD, id: body.user.id, token: body.accessToken };
}

// Per-VU user cache so each VU registers once and reuses its token.
let vuUser = null;
export function vuSession(prefix) {
  if (!vuUser) vuUser = registerUser(`${prefix}-vu${__VU}`);
  return vuUser;
}

// Common thresholds: <1% errors and a per-flow p95 latency budget (ms).
export function thresholds(p95ByName) {
  const t = { http_req_failed: ['rate<0.01'], checks: ['rate>0.99'] };
  for (const [name, p95] of Object.entries(p95ByName)) {
    t[`http_req_duration{name:${name}}`] = [`p(95)<${p95}`];
  }
  return t;
}

export const stages = [
  { duration: __ENV.RAMP || '15s', target: Number(__ENV.VUS || 10) },
  { duration: __ENV.HOLD || '45s', target: Number(__ENV.VUS || 10) },
  { duration: '10s', target: 0 },
];
