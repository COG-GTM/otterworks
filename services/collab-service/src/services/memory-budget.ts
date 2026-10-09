/**
 * Tracks the encoded size of every Yjs document held in memory so the
 * service can refuse growth before the pod's memory limit is reached.
 */
export class DocumentMemoryBudget {
  private sizes: Map<string, number> = new Map();
  private totalBytes = 0;

  constructor(readonly maxTotalBytes: number) {}

  get(key: string): number {
    return this.sizes.get(key) ?? 0;
  }

  set(key: string, bytes: number): void {
    this.totalBytes += bytes - this.get(key);
    this.sizes.set(key, bytes);
  }

  release(key: string): void {
    this.totalBytes -= this.get(key);
    this.sizes.delete(key);
  }

  wouldExceed(key: string, bytes: number): boolean {
    return this.totalBytes - this.get(key) + bytes > this.maxTotalBytes;
  }

  exceeded(): boolean {
    return this.totalBytes > this.maxTotalBytes;
  }

  get total(): number {
    return this.totalBytes;
  }
}
