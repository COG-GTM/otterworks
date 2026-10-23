import { loadConfig } from '../config';

describe('loadConfig JWT secret', () => {
  const original = process.env.JWT_SECRET;

  afterEach(() => {
    if (original === undefined) {
      delete process.env.JWT_SECRET;
    } else {
      process.env.JWT_SECRET = original;
    }
  });

  it('throws when JWT_SECRET is unset instead of falling back to a built-in key', () => {
    delete process.env.JWT_SECRET;
    expect(() => loadConfig()).toThrow('JWT_SECRET environment variable is required');
  });

  it('throws when JWT_SECRET is blank', () => {
    process.env.JWT_SECRET = '   ';
    expect(() => loadConfig()).toThrow('JWT_SECRET environment variable is required');
  });

  it('uses the configured JWT_SECRET', () => {
    process.env.JWT_SECRET = 'configured-secret';
    expect(loadConfig().jwt.secret).toBe('configured-secret');
  });
});
