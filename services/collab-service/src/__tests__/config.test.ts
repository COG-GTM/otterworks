import { loadConfig, requireJwtSecret } from '../config';

describe('JWT secret configuration', () => {
  const original = process.env.JWT_SECRET;

  afterEach(() => {
    if (original === undefined) {
      delete process.env.JWT_SECRET;
    } else {
      process.env.JWT_SECRET = original;
    }
  });

  it('refuses to start when JWT_SECRET is unset', () => {
    delete process.env.JWT_SECRET;
    expect(() => loadConfig()).toThrow(
      'JWT_SECRET environment variable is required but not set',
    );
  });

  it('refuses to start when JWT_SECRET is blank', () => {
    process.env.JWT_SECRET = '   ';
    expect(() => loadConfig()).toThrow('JWT_SECRET');
  });

  it('uses the configured JWT_SECRET', () => {
    process.env.JWT_SECRET = 'a-per-environment-secret';
    expect(loadConfig().jwt.secret).toBe('a-per-environment-secret');
  });

  it('has no built-in fallback secret', () => {
    expect(() => requireJwtSecret(undefined)).toThrow();
    expect(() => requireJwtSecret('')).toThrow();
  });
});
