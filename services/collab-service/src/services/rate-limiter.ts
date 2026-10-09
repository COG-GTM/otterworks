export interface RateLimit {
  limit: number;
  windowMs: number;
}

interface Window {
  start: number;
  count: number;
}

const PRUNE_THRESHOLD = 10000;

/** Fixed-window counter keyed by an arbitrary string (socket, user or document id). */
export class FixedWindowRateLimiter {
  private windows: Map<string, Window> = new Map();

  constructor(
    private readonly rule: RateLimit,
    private readonly now: () => number = Date.now,
  ) {}

  tryConsume(key: string): boolean {
    const t = this.now();
    if (this.windows.size > PRUNE_THRESHOLD) this.prune();

    let window = this.windows.get(key);
    if (!window || t - window.start >= this.rule.windowMs) {
      window = { start: t, count: 0 };
      this.windows.set(key, window);
    }
    if (window.count >= this.rule.limit) return false;
    window.count += 1;
    return true;
  }

  reset(key: string): void {
    this.windows.delete(key);
  }

  prune(): void {
    const t = this.now();
    for (const [key, window] of this.windows) {
      if (t - window.start >= this.rule.windowMs) this.windows.delete(key);
    }
  }

  get size(): number {
    return this.windows.size;
  }
}
