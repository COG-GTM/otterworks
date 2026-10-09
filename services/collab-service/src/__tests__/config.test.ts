import { loadConfig, MIN_JWT_SECRET_BYTES } from '../config';

describe('loadConfig JWT secret', () => {
  const originalSecret = process.env.JWT_SECRET;

  afterEach(() => {
    if (originalSecret === undefined) {
      delete process.env.JWT_SECRET;
    } else {
      process.env.JWT_SECRET = originalSecret;
    }
  });

  it('throws when JWT_SECRET is unset', () => {
    delete process.env.JWT_SECRET;
    expect(() => loadConfig()).toThrow(
      'JWT_SECRET environment variable is required but not set',
    );
  });

  it('throws when JWT_SECRET is empty', () => {
    process.env.JWT_SECRET = '';
    expect(() => loadConfig()).toThrow(
      'JWT_SECRET environment variable is required but not set',
    );
  });

  it('throws when JWT_SECRET is shorter than the minimum length', () => {
    process.env.JWT_SECRET = 'a'.repeat(MIN_JWT_SECRET_BYTES - 1);
    expect(() => loadConfig()).toThrow(`at least ${MIN_JWT_SECRET_BYTES} bytes`);
  });

  it('measures the minimum length in UTF-8 bytes', () => {
    process.env.JWT_SECRET = '\u00e9'.repeat(MIN_JWT_SECRET_BYTES / 2);
    expect(loadConfig().jwt.secret).toBe(process.env.JWT_SECRET);
  });

  it('never falls back to the former hard-coded secret', () => {
    delete process.env.JWT_SECRET;
    let secret: string | undefined;
    try {
      secret = loadConfig().jwt.secret;
    } catch {
      secret = undefined;
    }
    expect(secret).toBeUndefined();
  });

  it('uses JWT_SECRET when it is long enough', () => {
    process.env.JWT_SECRET = 'x'.repeat(MIN_JWT_SECRET_BYTES);
    expect(loadConfig().jwt.secret).toBe('x'.repeat(MIN_JWT_SECRET_BYTES));
  });
});
