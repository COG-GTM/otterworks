// auth-service (Spring Boot), hit directly on its own port.
import http from 'k6/http';
import { buildScenarios, registerEndpoints, record, jsonParams, createUser, summarize } from './lib/common.js';

const BASE = __ENV.AUTH_URL || 'http://localhost:8081';
const ENDPOINTS = ['auth_login', 'auth_get_profile', 'auth_update_profile'];
registerEndpoints(ENDPOINTS);

export const options = {
  scenarios: buildScenarios(ENDPOINTS),
  summaryTrendStats: ['p(50)', 'p(95)', 'p(99)', 'count'],
};

export function setup() {
  return createUser(BASE, 'auth');
}

export function run(user) {
  const name = __ENV.ENDPOINT;
  if (name === 'auth_login') {
    const res = http.post(`${BASE}/api/v1/auth/login`,
      JSON.stringify({ email: user.email, password: user.password }), jsonParams());
    record(name, res, 200);
  } else if (name === 'auth_get_profile') {
    record(name, http.get(`${BASE}/api/v1/auth/profile`, jsonParams(user.token)), 200);
  } else if (name === 'auth_update_profile') {
    const res = http.put(`${BASE}/api/v1/auth/profile`,
      JSON.stringify({ displayName: `Latency ${__ITER % 100}` }), jsonParams(user.token));
    record(name, res, 200);
  }
}

export const handleSummary = summarize('auth-service', ENDPOINTS);
