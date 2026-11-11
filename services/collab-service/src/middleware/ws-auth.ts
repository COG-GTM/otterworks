import { randomBytes } from 'crypto';
import type { IncomingMessage } from 'http';
import jwt from 'jsonwebtoken';

export const DEFAULT_WS_TICKET_TTL_MS = 30_000;

interface TicketEntry {
  userId: string;
  expiresAt: number;
}

export interface IssuedTicket {
  ticket: string;
  expiresInSeconds: number;
}

/**
 * Short-lived, single-use tickets that let browser y-websocket clients (which
 * cannot set an Authorization header on a WebSocket upgrade) authenticate
 * without putting their long-lived JWT in the URL.
 */
export class WsTicketStore {
  private readonly tickets = new Map<string, TicketEntry>();

  constructor(
    private readonly ttlMs: number = DEFAULT_WS_TICKET_TTL_MS,
    private readonly now: () => number = Date.now,
  ) {}

  issue(userId: string): IssuedTicket {
    this.prune();
    const ticket = randomBytes(32).toString('base64url');
    this.tickets.set(ticket, { userId, expiresAt: this.now() + this.ttlMs });
    return { ticket, expiresInSeconds: Math.ceil(this.ttlMs / 1000) };
  }

  consume(ticket: string): string | null {
    const entry = this.tickets.get(ticket);
    if (!entry) return null;
    this.tickets.delete(ticket);
    return entry.expiresAt > this.now() ? entry.userId : null;
  }

  prune(): void {
    const now = this.now();
    for (const [ticket, entry] of this.tickets) {
      if (entry.expiresAt <= now) this.tickets.delete(ticket);
    }
  }

  get size(): number {
    return this.tickets.size;
  }
}

export function verifyBearerToken(
  authorization: string | undefined,
  jwtSecret: string,
): { userId: string } | null {
  if (!authorization?.startsWith('Bearer ')) return null;
  const token = authorization.slice('Bearer '.length).trim();
  if (!token) return null;
  try {
    const decoded = jwt.verify(token, jwtSecret) as jwt.JwtPayload;
    return decoded.sub ? { userId: decoded.sub } : null;
  } catch {
    return null;
  }
}

/**
 * Authenticates a y-websocket upgrade from the Authorization header or a
 * single-use `ticket` query parameter. JWTs in the query string are not
 * accepted, so long-lived credentials never appear in request URLs.
 */
export function authenticateUpgrade(
  request: IncomingMessage,
  jwtSecret: string,
  ticketStore: WsTicketStore,
): { userId: string } | null {
  const fromHeader = verifyBearerToken(request.headers.authorization, jwtSecret);
  if (fromHeader) return fromHeader;

  const url = new URL(request.url || '', 'http://localhost');
  const ticket = url.searchParams.get('ticket');
  if (!ticket) return null;
  const userId = ticketStore.consume(ticket);
  return userId ? { userId } : null;
}
