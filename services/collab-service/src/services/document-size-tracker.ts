import * as Y from 'yjs';

/**
 * Enforces a per-document cap on encoded Yjs state size. Sizes are tracked
 * incrementally (an upper bound) and recomputed exactly only when the bound
 * would exceed the cap, so the common path never re-encodes the document.
 */
export class DocumentSizeTracker {
  private sizes: Map<string, number> = new Map();

  constructor(private readonly maxBytes: number) {}

  get limit(): number {
    return this.maxBytes;
  }

  fits(documentId: string, doc: Y.Doc, incomingBytes: number): boolean {
    if (incomingBytes > this.maxBytes) return false;
    let size = this.sizes.get(documentId);
    if (size === undefined || size + incomingBytes > this.maxBytes) {
      size = Y.encodeStateAsUpdate(doc).byteLength;
      this.sizes.set(documentId, size);
    }
    return size + incomingBytes <= this.maxBytes;
  }

  add(documentId: string, bytes: number): void {
    const size = this.sizes.get(documentId);
    if (size !== undefined) this.sizes.set(documentId, size + bytes);
  }

  set(documentId: string, bytes: number): void {
    this.sizes.set(documentId, bytes);
  }

  delete(documentId: string): void {
    this.sizes.delete(documentId);
  }
}

export function base64DecodedLength(value: string): number {
  const padding = value.endsWith('==') ? 2 : value.endsWith('=') ? 1 : 0;
  return Math.floor((value.length * 3) / 4) - padding;
}
