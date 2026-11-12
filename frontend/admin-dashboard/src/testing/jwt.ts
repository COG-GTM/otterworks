function base64Url(value: object): string {
  return btoa(JSON.stringify(value)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/** Builds an unsigned JWT-shaped string for specs; the dashboard only reads its claims. */
export function unsignedJwt(claims: Record<string, unknown>): string {
  return [base64Url({ alg: 'none', typ: 'JWT' }), base64Url(claims), 'sig'].join('.');
}

export function futureExp(seconds = 3600): number {
  return Math.floor(Date.now() / 1000) + seconds;
}
