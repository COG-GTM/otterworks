import { MOCK_AUDIT_EVENTS } from './audit.mock';
import { MOCK_USER_ACTIVITIES } from './users.mock';

// RFC 5737 documentation ranges: never routable, so fixtures can't point at real hosts.
const DOCUMENTATION_RANGES = ['192.0.2.', '198.51.100.', '203.0.113.'];

function isDocumentationAddress(ip: string): boolean {
  return DOCUMENTATION_RANGES.some(prefix => ip.startsWith(prefix));
}

describe('mock data IP addresses', () => {
  it('uses only RFC 5737 documentation addresses in audit events', () => {
    const offenders = MOCK_AUDIT_EVENTS.filter(e => !isDocumentationAddress(e.ipAddress));
    expect(offenders.map(e => `${e.id}: ${e.ipAddress}`)).toEqual([]);
  });

  it('uses only RFC 5737 documentation addresses in user activity', () => {
    const offenders = MOCK_USER_ACTIVITIES.filter(a => a.ipAddress && !isDocumentationAddress(a.ipAddress));
    expect(offenders.map(a => `${a.id}: ${a.ipAddress}`)).toEqual([]);
  });
});
