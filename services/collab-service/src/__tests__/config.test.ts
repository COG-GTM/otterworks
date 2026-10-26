import { loadConfig, MIN_JWT_SECRET_BYTES, requireJwtSecret } from '../config';

const STRONG_SECRET = 'a'.repeat(MIN_JWT_SECRET_BYTES);

describe('requireJwtSecret', () => {
  it('rejects a missing secret', () => {
    expect(() => requireJwtSecret(undefined)).toThrow(
      'JWT_SECRET environment variable is required',
    );
  });

  it('rejects an empty or whitespace-only secret', () => {
    expect(() => requireJwtSecret('')).toThrow('required');
    expect(() => requireJwtSecret('   ')).toThrow('required');
  });

  it('rejects the old public default', () => {
    expect(() => requireJwtSecret('otterworks-dev-secret')).toThrow(
      'publicly known default',
    );
  });

  it('rejects the docker-compose local-dev default only in production', () => {
    const composeDefault = 'otterworks-local-dev-jwt-secret-change-me-in-production';
    expect(() => requireJwtSecret(composeDefault, 'production')).toThrow(
      'publicly known default',
    );
    expect(requireJwtSecret(composeDefault, 'development')).toBe(composeDefault);
    expect(requireJwtSecret(composeDefault, undefined)).toBe(composeDefault);
  });

  it('rejects a secret shorter than the minimum length', () => {
    expect(() => requireJwtSecret('a'.repeat(MIN_JWT_SECRET_BYTES - 1))).toThrow(
      `at least ${MIN_JWT_SECRET_BYTES} bytes`,
    );
  });

  it('accepts a secret of the minimum length', () => {
    expect(requireJwtSecret(STRONG_SECRET)).toBe(STRONG_SECRET);
  });
});

describe('loadConfig', () => {
  const original = process.env.JWT_SECRET;

  afterEach(() => {
    if (original === undefined) {
      delete process.env.JWT_SECRET;
    } else {
      process.env.JWT_SECRET = original;
    }
  });

  it('refuses to load when JWT_SECRET is unset', () => {
    delete process.env.JWT_SECRET;
    expect(() => loadConfig()).toThrow('JWT_SECRET environment variable is required');
  });

  it('uses JWT_SECRET from the environment', () => {
    process.env.JWT_SECRET = STRONG_SECRET;
    expect(loadConfig().jwt.secret).toBe(STRONG_SECRET);
  });
});
