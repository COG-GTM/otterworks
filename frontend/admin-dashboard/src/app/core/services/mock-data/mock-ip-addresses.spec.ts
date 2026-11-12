import { MOCK_AUDIT_EVENTS } from './audit.mock';
import { MOCK_USER_ACTIVITIES } from './users.mock';

// RFC 5737 documentation ranges: never routable, so sample data can't point at a real host.
const DOCUMENTATION_RANGES = ['192.0.2.', '198.51.100.', '203.0.113.'];

describe('mock data IP addresses', () => {
  const ipAddresses = [
    ...MOCK_AUDIT_EVENTS.map((e) => e.ipAddress),
    ...MOCK_USER_ACTIVITIES.map((a) => a.ipAddress ?? ''),
  ].filter((ip) => ip !== '');

  it('only uses RFC 5737 documentation addresses', () => {
    expect(ipAddresses.length).toBeGreaterThan(0);
    const outside = ipAddresses.filter((ip) => !DOCUMENTATION_RANGES.some((range) => ip.startsWith(range)));
    expect(outside).toEqual([]);
  });
});
