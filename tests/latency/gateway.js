// api-gateway (Go): the gateway's own health route plus one proxied read and
// one proxied write. Keep RATE * concurrent endpoints under the gateway's
// per-IP limit (RATE_LIMIT_RPS, default 100).
import http from 'k6/http';
import { buildScenarios, registerEndpoints, record, jsonParams, createUser, summarize } from './lib/common.js';

const BASE = __ENV.GATEWAY_URL || 'http://localhost:8080';
const ENDPOINTS = ['gateway_health', 'gateway_proxy_get_profile', 'gateway_proxy_record_audit'];
registerEndpoints(ENDPOINTS);

export const options = {
  scenarios: buildScenarios(ENDPOINTS),
  summaryTrendStats: ['p(50)', 'p(95)', 'p(99)', 'count'],
};

export function setup() {
  return createUser(BASE, 'gateway');
}

export function run(user) {
  const name = __ENV.ENDPOINT;
  if (name === 'gateway_health') {
    record(name, http.get(`${BASE}/health`), 200);
  } else if (name === 'gateway_proxy_get_profile') {
    record(name, http.get(`${BASE}/api/v1/auth/profile`, jsonParams(user.token)), 200);
  } else if (name === 'gateway_proxy_record_audit') {
    const body = JSON.stringify({
      userId: user.userId, action: 'file.view', resourceType: 'file',
      resourceId: `gw-latency-${__ITER % 50}`, details: { source: 'latency-test' },
    });
    record(name, http.post(`${BASE}/api/v1/audit/events`, body, jsonParams(user.token)), 201);
  }
}

export const handleSummary = summarize('api-gateway', ENDPOINTS);
