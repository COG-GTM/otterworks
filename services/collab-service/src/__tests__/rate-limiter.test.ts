import { FixedWindowRateLimiter } from '../services/rate-limiter';

describe('FixedWindowRateLimiter', () => {
  it('allows up to the limit per window and then rejects', () => {
    let now = 0;
    const limiter = new FixedWindowRateLimiter({ limit: 2, windowMs: 1000 }, () => now);
    expect(limiter.tryConsume('a')).toBe(true);
    expect(limiter.tryConsume('a')).toBe(true);
    expect(limiter.tryConsume('a')).toBe(false);
    now = 999;
    expect(limiter.tryConsume('a')).toBe(false);
    now = 1000;
    expect(limiter.tryConsume('a')).toBe(true);
  });

  it('tracks keys independently', () => {
    const limiter = new FixedWindowRateLimiter({ limit: 1, windowMs: 1000 }, () => 0);
    expect(limiter.tryConsume('a')).toBe(true);
    expect(limiter.tryConsume('b')).toBe(true);
    expect(limiter.tryConsume('a')).toBe(false);
  });

  it('reset clears a key and prune drops expired windows', () => {
    let now = 0;
    const limiter = new FixedWindowRateLimiter({ limit: 1, windowMs: 100 }, () => now);
    limiter.tryConsume('a');
    limiter.tryConsume('b');
    limiter.reset('a');
    expect(limiter.tryConsume('a')).toBe(true);
    now = 100;
    limiter.prune();
    expect(limiter.size).toBe(0);
  });
});
