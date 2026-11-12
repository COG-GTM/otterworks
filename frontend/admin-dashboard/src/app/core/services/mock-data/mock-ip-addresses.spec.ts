import { MOCK_AUDIT_EVENTS } from './audit.mock';
import { MOCK_USER_ACTIVITIES } from './users.mock';

// RFC 5737 documentation ranges: never routable, so safe to hardcode in fixtures.
const DOCUMENTATION_RANGES = [/^192\.0\.2\.\d{1,3}$/, /^198\.51\.100\.\d{1,3}$/, /^203\.0\.113\.\d{1,3}$/];

describe('mock data IP addresses', () => {
  const addresses = [
    ...MOCK_AUDIT_EVENTS.map((event) => event.ipAddress),
    ...MOCK_USER_ACTIVITIES.map((activity) => activity.ipAddress),
  ].filter((ip): ip is string => !!ip);

  it('has IP addresses to check', () => {
    expect(addresses.length).toBeGreaterThan(0);
  });

  it('uses only RFC 5737 documentation addresses', () => {
    const offending = addresses.filter((ip) => !DOCUMENTATION_RANGES.some((range) => range.test(ip)));
    expect(offending).toEqual([]);
  });
});
