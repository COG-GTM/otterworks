// auth-service (Spring Boot, :8081): register (write), login (write), profile (read).
import http from 'k6/http';
import { check, fail } from 'k6';
import { buildOptions, makeSummary, runId } from './lib/latency.js';

const BASE = __ENV.AUTH_URL || 'http://localhost:8081';
const JSON_HDR = { headers: { 'Content-Type': 'application/json' } };

export const options = buildOptions(['auth_register', 'auth_login', 'auth_profile']);

export function setup() {
  const id = runId();
  const email = `latency-${id}@otterworks.test`;
  const password = 'LatencyCheck-2026!';
  const reg = http.post(`${BASE}/api/v1/auth/register`, JSON.stringify({ email, password, displayName: 'Latency Check' }), JSON_HDR);
  if (reg.status !== 201 && reg.status !== 200) fail(`register failed: ${reg.status} ${reg.body}`);
  const token = reg.json('accessToken');
  for (let i = 0; i < 20; i++) {
    http.post(`${BASE}/api/v1/auth/login`, JSON.stringify({ email, password }), JSON_HDR);
    http.get(`${BASE}/api/v1/auth/profile`, { headers: { Authorization: `Bearer ${token}` } });
  }
  return { id, email, password, token };
}

export function auth_register(d) {
  const email = `latency-${d.id}-${__VU}-${__ITER}@otterworks.test`;
  const r = http.post(`${BASE}/api/v1/auth/register`, JSON.stringify({ email, password: d.password, displayName: 'Latency Load' }), JSON_HDR);
  check(r, { 'register 2xx': (res) => res.status === 201 || res.status === 200 });
}

export function auth_login(d) {
  const r = http.post(`${BASE}/api/v1/auth/login`, JSON.stringify({ email: d.email, password: d.password }), JSON_HDR);
  check(r, { 'login 200': (res) => res.status === 200 });
}

export function auth_profile(d) {
  const r = http.get(`${BASE}/api/v1/auth/profile`, { headers: { Authorization: `Bearer ${d.token}` } });
  check(r, { 'profile 200': (res) => res.status === 200 });
}

export const handleSummary = makeSummary('auth-service');
