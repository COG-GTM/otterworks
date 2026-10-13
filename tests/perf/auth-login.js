// Auth login: POST /api/v1/auth/login (bcrypt verify + JWT issue) and an authenticated profile read.
import http from 'k6/http';
import { check, sleep } from 'k6';
import { BASE_URL, JSON_HEADERS, authHeaders, registerUser, stages, thresholds } from './lib/common.js';

export const options = {
  stages,
  thresholds: thresholds({ auth_login: 800, auth_profile: 300 }),
};

export function setup() {
  // A small pool of pre-registered users, shared by all VUs.
  return { users: Array.from({ length: 5 }, (_, i) => registerUser(`perf-login${i}`)) };
}

export default function (data) {
  const user = data.users[__ITER % data.users.length];
  const res = http.post(
    `${BASE_URL}/api/v1/auth/login`,
    JSON.stringify({ email: user.email, password: user.password }),
    { headers: JSON_HEADERS, tags: { name: 'auth_login' } },
  );
  check(res, {
    'login 200': (r) => r.status === 200,
    'login returns token': (r) => !!r.json('accessToken'),
  });
  const profile = http.get(`${BASE_URL}/api/v1/auth/profile`, {
    headers: authHeaders(res.json('accessToken')),
    tags: { name: 'auth_profile' },
  });
  check(profile, { 'profile 200': (r) => r.status === 200 });
  sleep(1);
}
