import jwt from 'jsonwebtoken';
import { verifyAccessToken } from '../middleware/auth';

const JWT_SECRET = 'test-secret-key-for-unit-tests';

function sign(payload: Record<string, unknown>): string {
  return jwt.sign(payload, JWT_SECRET, { expiresIn: '1h' }); // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
}

describe('verifyAccessToken', () => {
  it('accepts an access token', () => {
    expect(verifyAccessToken(sign({ sub: 'user-1', type: 'access' }), JWT_SECRET).sub).toBe('user-1');
  });

  it('accepts an untyped token as an access token', () => {
    expect(verifyAccessToken(sign({ sub: 'user-1' }), JWT_SECRET).sub).toBe('user-1');
  });

  it('rejects a refresh token', () => {
    const refresh = sign({ sub: 'user-1', type: 'refresh', jti: 'abc' });
    expect(() => verifyAccessToken(refresh, JWT_SECRET)).toThrow('refresh tokens cannot be used as access tokens');
  });

  it('rejects a token signed with another secret', () => {
    const forged = jwt.sign({ sub: 'user-1', type: 'access' }, 'another-secret'); // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
    expect(() => verifyAccessToken(forged, JWT_SECRET)).toThrow();
  });
});
