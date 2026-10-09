import jwt from 'jsonwebtoken';
import type { Socket } from 'socket.io';
import {
  createAuthMiddleware,
  DEFAULT_TOKEN_BINDING,
  verifyToken,
} from '../middleware/auth';

const SECRET = 'test-secret-key-for-unit-tests'; // nosemgrep: javascript.jsonwebtoken.security.jwt-hardcode.hardcoded-jwt-secret
const TENANT_A = {
  issuer: DEFAULT_TOKEN_BINDING.issuer,
  audience: 'otterworks-tenant-a',
};

const logger = {
  info: jest.fn(),
  warn: jest.fn(),
  error: jest.fn(),
  debug: jest.fn(),
} as never;

function sign(claims: Record<string, unknown>): string {
  return jwt.sign({ sub: 'user-1', roles: ['OWNER'], ...claims }, SECRET, {
    algorithm: 'HS512',
    expiresIn: '1h',
  });
}

function connect(token: string): Error | undefined {
  const socket = {
    id: 's1',
    handshake: { auth: { token }, headers: {} },
  } as unknown as Socket;
  let result: Error | undefined;
  createAuthMiddleware(
    SECRET,
    logger,
    TENANT_A,
  )(socket, (err) => {
    result = err as Error | undefined;
  });
  return result;
}

describe('collab token binding', () => {
  it("accepts a token minted for this tenant's issuer and audience", () => {
    const token = sign({ iss: TENANT_A.issuer, aud: TENANT_A.audience });
    expect(verifyToken(token, SECRET, TENANT_A).sub).toBe('user-1');
    expect(connect(token)).toBeUndefined();
  });

  it.each([
    ['another tenant audience', { iss: TENANT_A.issuer, aud: 'otterworks-tenant-b' }],
    ['a foreign issuer', { iss: 'evil-issuer', aud: TENANT_A.audience }],
    ['no audience', { iss: TENANT_A.issuer }],
    ['no issuer', { aud: TENANT_A.audience }],
  ])(
    'rejects a token with %s even when signed with the same secret',
    (_label, claims) => {
      const token = sign(claims);
      expect(() => verifyToken(token, SECRET, TENANT_A)).toThrow();
      expect(connect(token)?.message).toBe('Invalid or expired token');
    },
  );

  it('defaults to the otterworks audience when no binding is passed', () => {
    const token = sign({
      iss: DEFAULT_TOKEN_BINDING.issuer,
      aud: DEFAULT_TOKEN_BINDING.audience,
    });
    expect(verifyToken(token, SECRET).sub).toBe('user-1');
    expect(() => verifyToken(sign({}), SECRET)).toThrow();
  });
});
