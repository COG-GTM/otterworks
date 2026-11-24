// Shared helpers for the platform latency scripts.
import http from 'k6/http';
import { check } from 'k6';
import { Trend, Rate } from 'k6/metrics';

export const RATE = Number(__ENV.RATE || 10);          // requests/second per endpoint
export const DURATION = __ENV.DURATION || '30s';       // measured window per endpoint
export const WARMUP = __ENV.WARMUP || '5s';             // unmeasured warmup per endpoint
export const OUT_DIR = __ENV.OUT_DIR || 'tests/latency/results';

// Builds one warmup + one measured scenario per endpoint. Endpoints run one
// after another so they never compete for CPU on the same machine.
export function buildScenarios(endpoints) {
  const scenarios = {};
  const warmupSec = parseDuration(WARMUP);
  const durationSec = parseDuration(DURATION);
  let offset = 0;
  for (const name of endpoints) {
    const base = {
      executor: 'constant-arrival-rate',
      rate: RATE,
      timeUnit: '1s',
      preAllocatedVUs: Math.max(5, RATE * 2),
      maxVUs: Math.max(20, RATE * 10),
      exec: 'run',
      env: { ENDPOINT: name },
    };
    if (warmupSec > 0) {
      scenarios[`warmup_${name}`] = { ...base, duration: `${warmupSec}s`, startTime: `${offset}s`,
        env: { ENDPOINT: name, MEASURE: '0' } };
      offset += warmupSec;
    }
    scenarios[name] = { ...base, duration: `${durationSec}s`, startTime: `${offset}s`,
      env: { ENDPOINT: name, MEASURE: '1' } };
    offset += durationSec;
  }
  return scenarios;
}

const trends = {};
const errors = {};
function trendFor(name) {
  if (!trends[name]) {
    trends[name] = new Trend(`latency_${name}`, true);
    errors[name] = new Rate(`errors_${name}`);
  }
  return [trends[name], errors[name]];
}

// Declares the per-endpoint metrics up front (k6 requires init-context creation).
export function registerEndpoints(endpoints) {
  for (const name of endpoints) trendFor(name);
}

export function record(name, res, expectedStatus) {
  const ok = check(res, { [`${name} status ${expectedStatus}`]: (r) => r.status === expectedStatus });
  if (__ENV.MEASURE !== '1') return;
  const [trend, err] = trendFor(name);
  // Only successful responses count toward latency, so fast errors can't pass a budget.
  if (ok) trend.add(res.timings.duration);
  err.add(!ok);
}

export function jsonParams(token, extraHeaders) {
  const headers = { 'Content-Type': 'application/json', ...(extraHeaders || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  return { headers };
}

// Registers a fresh user and returns { email, password, token, userId }.
export function createUser(baseUrl, label) {
  const email = `latency-${label}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
  const password = 'LatencyTest#2026';
  const res = http.post(`${baseUrl}/api/v1/auth/register`,
    JSON.stringify({ email, password, displayName: `Latency ${label}` }), jsonParams());
  if (res.status !== 201) {
    throw new Error(`register failed: ${res.status} ${res.body}`);
  }
  const body = res.json();
  return { email, password, token: body.accessToken, userId: body.user.id };
}

// Writes { service, rate, duration, endpoints: { name: {p50,p95,p99,count,error_rate} } }.
export function summarize(service, endpoints) {
  return (data) => {
    const out = { service, rate_per_sec: RATE, duration: DURATION, endpoints: {} };
    for (const name of endpoints) {
      const t = data.metrics[`latency_${name}`];
      const e = data.metrics[`errors_${name}`];
      // Every endpoint gets a row; count 0 means no successful sample, which the check rejects.
      out.endpoints[name] = {
        p50: t ? round(t.values['p(50)']) : null,
        p95: t ? round(t.values['p(95)']) : null,
        p99: t ? round(t.values['p(99)']) : null,
        count: t ? t.values.count : 0,
        error_rate: e ? round(e.values.rate, 4) : null,
      };
    }
    const lines = Object.entries(out.endpoints).map(([n, v]) =>
      v.count ? `${n.padEnd(34)} p50=${v.p50}ms p95=${v.p95}ms p99=${v.p99}ms n=${v.count} err=${v.error_rate}`
        : `${n.padEnd(34)} no successful samples err=${v.error_rate}`);
    return {
      [`${OUT_DIR}/${service}.json`]: JSON.stringify(out, null, 2) + '\n',
      stdout: `\n${service}\n${lines.join('\n')}\n`,
    };
  };
}

function round(v, digits = 1) {
  const f = 10 ** digits;
  return Math.round(v * f) / f;
}

function parseDuration(s) {
  const m = String(s).match(/^(\d+)(ms|s|m)?$/);
  if (!m) throw new Error(`bad duration ${s}`);
  const n = Number(m[1]);
  return m[2] === 'm' ? n * 60 : m[2] === 'ms' ? n / 1000 : n;
}
