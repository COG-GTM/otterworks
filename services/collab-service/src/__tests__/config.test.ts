import { loadConfig } from '../config';

describe('loadConfig', () => {
  const originalSecret = process.env.JWT_SECRET;

  afterEach(() => {
    if (originalSecret === undefined) {
      delete process.env.JWT_SECRET;
    } else {
      process.env.JWT_SECRET = originalSecret;
    }
  });

  it('throws when JWT_SECRET is not set', () => {
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

  it('uses the JWT_SECRET from the environment', () => {
    process.env.JWT_SECRET = 'secret-from-the-environment';

    expect(loadConfig().jwt.secret).toBe('secret-from-the-environment');
  });
});
