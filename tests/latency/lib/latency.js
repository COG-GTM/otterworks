// Shared helpers for the platform latency scripts: per-endpoint scenarios run
// one after another at a fixed arrival rate, with a p95 threshold per endpoint
// taken from budgets.json.
const budgets = JSON.parse(open('../budgets.json'));

export const RATE = parseInt(__ENV.RATE || '10', 10);
export const DURATION_S = parseInt(__ENV.DURATION_S || '30', 10);
const MAX_VUS = parseInt(__ENV.MAX_VUS || '100', 10);
const GAP_S = 2;

function selected(endpoints) {
  if (!__ENV.ENDPOINTS) return endpoints;
  const wanted = __ENV.ENDPOINTS.split(',').map((s) => s.trim());
  return endpoints.filter((e) => wanted.includes(e));
}

export function buildOptions(endpoints) {
  const active = selected(endpoints);
  const scenarios = {};
  const thresholds = {};
  active.forEach((name, i) => {
    const budget = budgets.endpoints[name];
    if (!budget) throw new Error(`no budget for endpoint ${name} in budgets.json`);
    scenarios[name] = {
      executor: 'constant-arrival-rate',
      exec: name,
      rate: RATE,
      timeUnit: '1s',
      duration: `${DURATION_S}s`,
      preAllocatedVUs: Math.min(20, MAX_VUS),
      maxVUs: MAX_VUS,
      startTime: `${i * (DURATION_S + GAP_S)}s`,
      tags: { endpoint: name },
    };
    thresholds[`http_req_duration{endpoint:${name}}`] = [`p(95)<${budget.p95_ms}`];
    thresholds[`http_req_failed{endpoint:${name}}`] = ['rate<0.01'];
    // Requests k6 could not start on schedule (all VUs busy) would otherwise be
    // left out of the p95, so any drop fails the gate.
    thresholds[`dropped_iterations{scenario:${name}}`] = ['count==0'];
  });
  return {
    scenarios,
    thresholds,
    summaryTrendStats: ['avg', 'min', 'med', 'p(95)', 'p(99)', 'max'],
    setupTimeout: '300s',
  };
}

export function makeSummary(service) {
  return (data) => {
    const rows = [];
    for (const [key, metric] of Object.entries(data.metrics)) {
      const m = key.match(/^http_req_duration\{endpoint:(.+)\}$/);
      if (!m) continue;
      const name = m[1];
      const failed = data.metrics[`http_req_failed{endpoint:${name}}`];
      const dropped = data.metrics[`dropped_iterations{scenario:${name}}`];
      const droppedCount = dropped ? dropped.values.count : 0;
      const v = metric.values;
      rows.push({
        service,
        endpoint: name,
        method_path: budgets.endpoints[name].request,
        requests: data.metrics[`http_reqs{endpoint:${name}}`]
          ? data.metrics[`http_reqs{endpoint:${name}}`].values.count
          : null,
        error_rate: failed ? failed.values.rate : null,
        dropped_requests: droppedCount,
        p50_ms: +v.med.toFixed(1),
        p95_ms: +v['p(95)'].toFixed(1),
        p99_ms: +v['p(99)'].toFixed(1),
        budget_p95_ms: budgets.endpoints[name].p95_ms,
        over_budget: v['p(95)'] >= budgets.endpoints[name].p95_ms || droppedCount > 0,
      });
    }
    rows.sort((a, b) => b.p95_ms - a.p95_ms);
    const lines = rows.map(
      (r) =>
        `${r.over_budget ? 'OVER' : ' ok '}  ${r.endpoint.padEnd(26)} p50=${String(r.p50_ms).padStart(7)}ms  p95=${String(r.p95_ms).padStart(7)}ms  p99=${String(r.p99_ms).padStart(7)}ms  budget(p95)<${r.budget_p95_ms}ms  errors=${((r.error_rate || 0) * 100).toFixed(2)}%  dropped=${r.dropped_requests}`,
    );
    const outDir = __ENV.RESULTS_DIR || 'results';
    return {
      stdout: `\n=== ${service} latency vs p95 budget (rate=${RATE}/s, ${DURATION_S}s per endpoint) ===\n${lines.join('\n')}\n`,
      [`${outDir}/${service}.json`]: JSON.stringify({ service, rate_per_s: RATE, duration_s: DURATION_S, endpoints: rows }, null, 2),
    };
  };
}

export const runId = () => `${Date.now()}-${Math.floor(Math.random() * 1e6)}`;
