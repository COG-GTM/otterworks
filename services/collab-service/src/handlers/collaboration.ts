import { Server as SocketIOServer, Socket } from 'socket.io';
import type { Logger } from 'pino';
import * as Y from 'yjs';
import { DocumentStore } from '../services/document-store';
import { DocumentMemoryBudget } from '../services/memory-budget';
import { FixedWindowRateLimiter, type RateLimit } from '../services/rate-limiter';
import { AwarenessService, type CursorPosition } from '../services/awareness';
import { extractUserFromSocket } from '../middleware/auth';
import { MetricsCollector } from '../metrics';
import { PresenceHandler } from './presence';

export interface CommentAnnotation {
  id: string;
  documentId: string;
  threadId: string;
  content: string;
  author: { userId: string; displayName: string };
  rangeStart: number;
  rangeEnd: number;
  createdAt: string;
  parentId?: string;
}

export interface CollaborationLimits {
  /** Largest decoded Yjs update accepted from a client. */
  maxUpdateBytes: number;
  /** Largest encoded Yjs state a single document may reach. */
  maxDocumentBytes: number;
  /** Combined encoded size of every document held in memory. */
  maxTotalDocumentBytes: number;
  maxDocumentsInMemory: number;
  /** Distinct documents one user may have open across all of their sockets. */
  maxDocumentsPerUser: number;
  /** Delay between an accepted update and the Redis write of the full state. */
  persistDebounceMs: number;
  socketUpdates: RateLimit;
  userUpdates: RateLimit;
  socketSnapshots: RateLimit;
  userSnapshots: RateLimit;
  documentSnapshots: RateLimit;
  userJoins: RateLimit;
}

export const DEFAULT_COLLABORATION_LIMITS: CollaborationLimits = {
  maxUpdateBytes: 256 * 1024,
  maxDocumentBytes: 2 * 1024 * 1024,
  maxTotalDocumentBytes: 64 * 1024 * 1024,
  maxDocumentsInMemory: 500,
  maxDocumentsPerUser: 10,
  persistDebounceMs: 2000,
  socketUpdates: { limit: 50, windowMs: 1000 },
  userUpdates: { limit: 100, windowMs: 1000 },
  socketSnapshots: { limit: 2, windowMs: 60000 },
  userSnapshots: { limit: 5, windowMs: 60000 },
  documentSnapshots: { limit: 10, windowMs: 60000 },
  userJoins: { limit: 30, windowMs: 60000 },
};

const MAX_DOCUMENT_ID_LENGTH = 256;
const MAX_HISTORY_LIMIT = 50;

class DocumentLimitError extends Error {}

export interface CollaborationDeps {
  io: SocketIOServer;
  documentStore: DocumentStore;
  awareness: AwarenessService;
  presenceHandler: PresenceHandler;
  metrics: MetricsCollector;
  logger: Logger;
  persistIntervalMs: number;
  snapshotIntervalMs: number;
  limits?: Partial<CollaborationLimits>;
  /** Shared with the y-websocket guard so both servers draw from one memory budget. */
  memoryBudget?: DocumentMemoryBudget;
}

export class CollaborationManager {
  private documents: Map<string, Y.Doc> = new Map();
  private documentInitPromises: Map<string, Promise<Y.Doc>> = new Map();
  private cleaningUp: Set<string> = new Set();
  private deps: CollaborationDeps;
  private persistTimer: NodeJS.Timeout | null = null;
  private snapshotTimer: NodeJS.Timeout | null = null;
  private limits: CollaborationLimits;
  private budget: DocumentMemoryBudget;
  private dirty: Set<string> = new Set();
  private changedSinceSnapshot: Set<string> = new Set();
  private lastModifiedBy: Map<string, string> = new Map();
  private persistTimers: Map<string, NodeJS.Timeout> = new Map();
  private socketDocuments: Map<string, { userId: string; documentId: string }> =
    new Map();
  private userDocuments: Map<string, Map<string, number>> = new Map();
  private socketUpdateLimiter: FixedWindowRateLimiter;
  private userUpdateLimiter: FixedWindowRateLimiter;
  private socketSnapshotLimiter: FixedWindowRateLimiter;
  private userSnapshotLimiter: FixedWindowRateLimiter;
  private documentSnapshotLimiter: FixedWindowRateLimiter;
  private userJoinLimiter: FixedWindowRateLimiter;

  constructor(deps: CollaborationDeps) {
    this.deps = deps;
    this.limits = { ...DEFAULT_COLLABORATION_LIMITS, ...deps.limits };
    this.budget =
      deps.memoryBudget ?? new DocumentMemoryBudget(this.limits.maxTotalDocumentBytes);
    this.socketUpdateLimiter = new FixedWindowRateLimiter(this.limits.socketUpdates);
    this.userUpdateLimiter = new FixedWindowRateLimiter(this.limits.userUpdates);
    this.socketSnapshotLimiter = new FixedWindowRateLimiter(this.limits.socketSnapshots);
    this.userSnapshotLimiter = new FixedWindowRateLimiter(this.limits.userSnapshots);
    this.documentSnapshotLimiter = new FixedWindowRateLimiter(
      this.limits.documentSnapshots,
    );
    this.userJoinLimiter = new FixedWindowRateLimiter(this.limits.userJoins);
  }

  getDocument(documentId: string): Y.Doc | undefined {
    return this.documents.get(documentId);
  }

  getDocumentCount(): number {
    return this.documents.size;
  }

  start(): void {
    const { io, logger } = this.deps;

    io.on('connection', (socket: Socket) => {
      this.deps.metrics.activeConnections.inc();
      logger.info({ socketId: socket.id }, 'client_connected');

      this.registerSocketHandlers(socket);

      socket.on('disconnect', (reason) => {
        this.handleDisconnect(socket, reason);
      });
    });

    this.startPersistenceLoop();
    this.startSnapshotLoop();
    logger.info('collaboration_manager_started');
  }

  async stop(): Promise<void> {
    if (this.persistTimer) clearInterval(this.persistTimer);
    if (this.snapshotTimer) clearInterval(this.snapshotTimer);
    for (const timer of this.persistTimers.values()) clearTimeout(timer);
    this.persistTimers.clear();

    // Final persistence pass: flush all in-memory documents to Redis before shutdown
    const { documentStore, logger } = this.deps;
    for (const [documentId, doc] of this.documents) {
      try {
        const state = Y.encodeStateAsUpdate(doc);
        await documentStore.saveDocumentState(documentId, Buffer.from(state));
        logger.info({ documentId }, 'document_persisted_on_shutdown');
      } catch (err) {
        logger.error({ err, documentId }, 'document_persist_on_shutdown_failed');
      }
    }

    logger.info('collaboration_manager_stopped');
  }

  private registerSocketHandlers(socket: Socket): void {
    socket.on('join-document', (data, ack) => this.handleJoinDocument(socket, data, ack));
    socket.on('leave-document', (data) => this.handleLeaveDocument(socket, data));
    socket.on('document-update', (data) => this.handleDocumentUpdate(socket, data));
    socket.on('cursor-update', (data) => this.handleCursorUpdate(socket, data));
    socket.on('typing-indicator', (data) => this.handleTypingIndicator(socket, data));
    socket.on('comment-add', (data) => this.handleCommentAdd(socket, data));
    socket.on('comment-update', (data) => this.handleCommentUpdate(socket, data));
    socket.on('comment-delete', (data) => this.handleCommentDelete(socket, data));
    socket.on('request-snapshot', (data) => this.handleRequestSnapshot(socket, data));
    socket.on('request-history', (data) => this.handleRequestHistory(socket, data));
  }

  private async handleJoinDocument(
    socket: Socket,
    data: { documentId: string },
    ack?: (response: { success: boolean; error?: string }) => void,
  ): Promise<void> {
    const documentId = data?.documentId;
    const { io, awareness, presenceHandler, metrics, logger } = this.deps;
    const user = extractUserFromSocket(socket);
    const room = `doc:${documentId}`;

    const rejection = this.checkJoinAllowed(socket, user.userId, documentId);
    if (rejection) {
      logger.warn(
        { documentId, userId: user.userId, socketId: socket.id, reason: rejection },
        'join_document_rejected',
      );
      metrics.connectionErrors.inc({ reason: 'join_rejected' });
      if (ack) ack({ success: false, error: rejection });
      return;
    }

    try {
      // If socket is already in another document, leave it first
      const oldDocId = awareness.getUserDocument(socket.id);
      if (oldDocId && oldDocId !== documentId) {
        const oldRoom = `doc:${oldDocId}`;
        socket.leave(oldRoom);
        awareness.removeUser(socket.id);
        this.untrackSocket(socket.id);
        socket.to(oldRoom).emit('user-left', {
          socketId: socket.id,
          userId: user.userId,
        });
        presenceHandler.broadcastPresenceUpdate(io, oldDocId);
        if (awareness.getDocumentUserCount(oldDocId) === 0) {
          this.persistAndCleanupDocument(oldDocId);
        }
        logger.info(
          { oldDocumentId: oldDocId, newDocumentId: documentId, socketId: socket.id },
          'user_switched_documents',
        );
      }

      await socket.join(room);
      logger.info(
        { documentId, userId: user.userId, socketId: socket.id },
        'user_joined_document',
      );

      // Get or create Yjs document (safe against concurrent joins)
      const doc = await this.getOrCreateDoc(documentId);
      this.trackSocket(socket.id, user.userId, documentId);

      // Register awareness
      const userAwareness = awareness.addUser(
        documentId,
        socket.id,
        user.userId,
        user.displayName,
        user.email,
      );

      // Sync document state to joining client
      const syncStart = Date.now();
      const state = Y.encodeStateAsUpdate(doc);
      socket.emit('sync-document', {
        documentId,
        state: Buffer.from(state).toString('base64'),
      });
      metrics.documentSyncDuration.observe((Date.now() - syncStart) / 1000);

      // Notify others
      socket.to(room).emit('user-joined', {
        userId: user.userId,
        displayName: user.displayName,
        color: userAwareness.color,
        socketId: socket.id,
      });

      // Send current presence to joining user
      presenceHandler.broadcastPresenceUpdate(io, documentId);
      metrics.messagesTotal.inc({ type: 'join-document' });

      if (ack) ack({ success: true });
    } catch (err) {
      logger.error({ err, documentId, socketId: socket.id }, 'join_document_failed');
      socket.leave(room);
      metrics.connectionErrors.inc({ reason: 'join_failed' });
      const error =
        err instanceof DocumentLimitError ? err.message : 'Failed to join document';
      if (ack) ack({ success: false, error });
    }
  }

  /** Returns a client-facing reason when the join must be refused, else null. */
  private checkJoinAllowed(
    socket: Socket,
    userId: string,
    documentId: unknown,
  ): string | null {
    if (
      typeof documentId !== 'string' ||
      documentId.length === 0 ||
      documentId.length > MAX_DOCUMENT_ID_LENGTH
    ) {
      return 'Invalid document id';
    }
    const current = this.socketDocuments.get(socket.id);
    if (current?.documentId === documentId) return null;

    if (!this.userJoinLimiter.tryConsume(userId)) {
      return 'Too many join requests';
    }

    const openDocs = this.userDocuments.get(userId);
    if (openDocs && !openDocs.has(documentId)) {
      // A switch releases the socket's current document if no other socket holds it
      const released = current && openDocs.get(current.documentId) === 1 ? 1 : 0;
      if (openDocs.size - released >= this.limits.maxDocumentsPerUser) {
        return 'Too many open documents';
      }
    }

    if (
      !this.documents.has(documentId) &&
      !this.documentInitPromises.has(documentId) &&
      this.documents.size + this.documentInitPromises.size >=
        this.limits.maxDocumentsInMemory
    ) {
      return 'Document capacity reached';
    }
    return null;
  }

  private trackSocket(socketId: string, userId: string, documentId: string): void {
    const current = this.socketDocuments.get(socketId);
    if (current?.documentId === documentId) return;
    if (current) this.untrackSocket(socketId);

    this.socketDocuments.set(socketId, { userId, documentId });
    let openDocs = this.userDocuments.get(userId);
    if (!openDocs) {
      openDocs = new Map();
      this.userDocuments.set(userId, openDocs);
    }
    openDocs.set(documentId, (openDocs.get(documentId) ?? 0) + 1);
  }

  private untrackSocket(socketId: string): void {
    const current = this.socketDocuments.get(socketId);
    if (!current) return;
    this.socketDocuments.delete(socketId);
    const openDocs = this.userDocuments.get(current.userId);
    if (!openDocs) return;
    const count = (openDocs.get(current.documentId) ?? 1) - 1;
    if (count > 0) openDocs.set(current.documentId, count);
    else openDocs.delete(current.documentId);
    if (openDocs.size === 0) this.userDocuments.delete(current.userId);
  }

  private handleLeaveDocument(socket: Socket, data: { documentId: string }): void {
    const { io, awareness, presenceHandler, metrics, logger } = this.deps;

    const mapping = awareness.removeUser(socket.id);
    this.untrackSocket(socket.id);
    // Use the document the awareness service actually tracked, falling back to client-provided id
    const trackedDocId = mapping?.documentId ?? data.documentId;
    const room = `doc:${trackedDocId}`;

    socket.leave(room);

    if (mapping) {
      socket.to(room).emit('user-left', { socketId: socket.id, userId: mapping.userId });
      presenceHandler.broadcastPresenceUpdate(io, trackedDocId);
    }
    metrics.messagesTotal.inc({ type: 'leave-document' });

    // Clean up empty documents from memory
    const userCount = awareness.getDocumentUserCount(trackedDocId);
    if (userCount === 0) {
      this.persistAndCleanupDocument(trackedDocId);
    }

    logger.info({ documentId: trackedDocId, socketId: socket.id }, 'user_left_document');
  }

  private async handleDocumentUpdate(
    socket: Socket,
    data: { documentId: string; update: unknown },
  ): Promise<void> {
    const { metrics, logger } = this.deps;
    const { documentId, update } = data;
    const room = `doc:${documentId}`;
    const user = extractUserFromSocket(socket);

    const doc = this.documents.get(documentId);
    if (!doc || this.socketDocuments.get(socket.id)?.documentId !== documentId) {
      logger.warn({ documentId, socketId: socket.id }, 'document_update_for_unknown_doc');
      return;
    }

    if (
      !this.socketUpdateLimiter.tryConsume(socket.id) ||
      !this.userUpdateLimiter.tryConsume(user.userId)
    ) {
      metrics.connectionErrors.inc({ reason: 'update_rate_limited' });
      socket.emit('document-update-error', {
        documentId,
        error: 'Too many updates',
      });
      return;
    }

    // Accept legacy JSON patches for API-flow clients while preserving Yjs updates for real editors.
    if (typeof update === 'string') {
      const updateBytes = Buffer.from(update, 'base64');
      const rejection = this.checkUpdateSize(documentId, doc, updateBytes.length);
      if (rejection) {
        logger.warn(
          {
            documentId,
            socketId: socket.id,
            bytes: updateBytes.length,
            reason: rejection,
          },
          'document_update_rejected',
        );
        metrics.connectionErrors.inc({ reason: 'update_too_large' });
        socket.emit('document-update-error', { documentId, error: rejection });
        return;
      }
      try {
        Y.applyUpdate(doc, new Uint8Array(updateBytes));
        // Upper bound until the next full encode measures the real size
        const estimate = this.docSize(documentId) + updateBytes.length;
        this.budget.set(this.budgetKey(documentId), estimate);
      } catch (err) {
        logger.error({ err, documentId, socketId: socket.id }, 'crdt_apply_failed');
        socket.emit('document-update-error', {
          documentId,
          error: 'Failed to apply update',
        });
        return;
      }
    }

    // Refresh the user's lastActive so active editors aren't evicted as stale
    this.deps.awareness.refreshActivity(socket.id);

    // Step 2: Broadcast to other clients immediately after successful CRDT apply
    socket.to(room).emit('document-update', { documentId, update });
    metrics.documentUpdatesTotal.inc();
    metrics.messagesTotal.inc({ type: 'document-update' });

    // Step 3: Debounced persistence; one full-state write per document per window
    this.markDirty(documentId, user.userId);
  }

  private checkUpdateSize(documentId: string, doc: Y.Doc, bytes: number): string | null {
    const { maxUpdateBytes, maxDocumentBytes } = this.limits;
    if (bytes > maxUpdateBytes) return 'Update exceeds size limit';

    const key = this.budgetKey(documentId);
    let size = this.docSize(documentId);
    if (size + bytes > maxDocumentBytes || this.budget.wouldExceed(key, size + bytes)) {
      // The tracked size is an upper bound; measure before refusing
      size = Y.encodeStateAsUpdate(doc).length;
      this.budget.set(key, size);
    }
    if (size + bytes > maxDocumentBytes) return 'Document size limit reached';
    if (this.budget.wouldExceed(key, size + bytes)) {
      return 'Server document capacity reached';
    }
    return null;
  }

  private budgetKey(documentId: string): string {
    return `io:${documentId}`;
  }

  private docSize(documentId: string): number {
    return this.budget.get(this.budgetKey(documentId));
  }

  private markDirty(documentId: string, userId: string): void {
    this.dirty.add(documentId);
    this.changedSinceSnapshot.add(documentId);
    this.lastModifiedBy.set(documentId, userId);
    if (this.persistTimers.has(documentId)) return;

    const timer = setTimeout(() => {
      this.persistTimers.delete(documentId);
      void this.persistDocument(documentId, 'save_state');
    }, this.limits.persistDebounceMs);
    timer.unref?.();
    this.persistTimers.set(documentId, timer);
  }

  private async persistDocument(documentId: string, operation: string): Promise<void> {
    const { documentStore, metrics, logger } = this.deps;
    const doc = this.documents.get(documentId);
    if (!doc || !this.dirty.has(documentId)) return;

    // Cleared before the await so updates arriving mid-write mark the doc again
    this.dirty.delete(documentId);
    const start = Date.now();
    try {
      const state = Y.encodeStateAsUpdate(doc);
      this.budget.set(this.budgetKey(documentId), state.length);
      await documentStore.saveDocumentState(
        documentId,
        Buffer.from(state),
        this.lastModifiedBy.get(documentId),
      );
      metrics.persistenceDuration.observe({ operation }, (Date.now() - start) / 1000);
      metrics.persistenceOperations.inc({ operation, status: 'success' });
    } catch (err) {
      this.dirty.add(documentId);
      logger.error({ err, documentId }, 'document_persist_failed');
      metrics.persistenceOperations.inc({ operation, status: 'error' });
    }
  }

  private handleCursorUpdate(
    socket: Socket,
    data: {
      documentId: string;
      cursor: CursorPosition | null;
      selection: CursorPosition | null;
    },
  ): void {
    const { awareness, metrics } = this.deps;
    const updatedAwareness = awareness.updateCursor(
      socket.id,
      data.cursor,
      data.selection,
    );

    if (updatedAwareness) {
      const room = `doc:${data.documentId}`;
      socket.to(room).emit('cursor-update', {
        socketId: socket.id,
        userId: updatedAwareness.userId,
        displayName: updatedAwareness.displayName,
        color: updatedAwareness.color,
        cursor: data.cursor,
        selection: data.selection,
      });
      metrics.presenceUpdatesTotal.inc();
    }
  }

  private handleTypingIndicator(
    socket: Socket,
    data: { documentId: string; isTyping: boolean },
  ): void {
    const { awareness } = this.deps;
    const updated = awareness.setTyping(socket.id, data.isTyping);

    if (updated) {
      const room = `doc:${data.documentId}`;
      socket.to(room).emit('typing-indicator', {
        socketId: socket.id,
        userId: updated.userId,
        displayName: updated.displayName,
        isTyping: data.isTyping,
      });
    }
  }

  private handleCommentAdd(
    socket: Socket,
    data: {
      documentId: string;
      comment: Omit<CommentAnnotation, 'author' | 'createdAt'>;
    },
  ): void {
    const { metrics } = this.deps;
    const user = extractUserFromSocket(socket);
    const room = `doc:${data.documentId}`;

    const fullComment: CommentAnnotation = {
      ...data.comment,
      documentId: data.documentId,
      author: { userId: user.userId, displayName: user.displayName },
      createdAt: new Date().toISOString(),
    };

    socket.to(room).emit('comment-added', fullComment);
    socket.emit('comment-added', fullComment);
    metrics.commentAnnotationsTotal.inc({ action: 'add' });
    metrics.messagesTotal.inc({ type: 'comment-add' });
  }

  private handleCommentUpdate(
    socket: Socket,
    data: {
      documentId: string;
      commentId: string;
      content: string;
    },
  ): void {
    const { metrics } = this.deps;
    const user = extractUserFromSocket(socket);
    const room = `doc:${data.documentId}`;

    const payload = {
      commentId: data.commentId,
      content: data.content,
      updatedBy: { userId: user.userId, displayName: user.displayName },
      updatedAt: new Date().toISOString(),
    };

    socket.to(room).emit('comment-updated', payload);
    metrics.commentAnnotationsTotal.inc({ action: 'update' });
    metrics.messagesTotal.inc({ type: 'comment-update' });
  }

  private handleCommentDelete(
    socket: Socket,
    data: { documentId: string; commentId: string },
  ): void {
    const { metrics } = this.deps;
    const user = extractUserFromSocket(socket);
    const room = `doc:${data.documentId}`;

    socket.to(room).emit('comment-deleted', {
      commentId: data.commentId,
      deletedBy: user.userId,
    });
    metrics.commentAnnotationsTotal.inc({ action: 'delete' });
    metrics.messagesTotal.inc({ type: 'comment-delete' });
  }

  private async handleRequestSnapshot(
    socket: Socket,
    data: { documentId: string; label?: string },
  ): Promise<void> {
    const { documentStore, logger } = this.deps;
    const user = extractUserFromSocket(socket);
    const { documentId } = data;
    const label = typeof data.label === 'string' ? data.label.slice(0, 200) : undefined;

    const doc = this.documents.get(documentId);
    if (!doc || this.socketDocuments.get(socket.id)?.documentId !== documentId) {
      socket.emit('snapshot-error', {
        documentId,
        error: 'Document not found',
      });
      return;
    }

    if (
      !this.socketSnapshotLimiter.tryConsume(socket.id) ||
      !this.userSnapshotLimiter.tryConsume(user.userId) ||
      !this.documentSnapshotLimiter.tryConsume(documentId)
    ) {
      socket.emit('snapshot-error', {
        documentId,
        error: 'Too many snapshot requests',
      });
      return;
    }

    try {
      const state = Y.encodeStateAsUpdate(doc);
      const snapshot = await documentStore.createSnapshot(
        documentId,
        Buffer.from(state),
        user.userId,
        label,
      );
      socket.emit('snapshot-created', snapshot);

      const room = `doc:${documentId}`;
      socket.to(room).emit('snapshot-created', snapshot);
    } catch (err) {
      logger.error({ err, documentId }, 'create_snapshot_failed');
      socket.emit('snapshot-error', {
        documentId,
        error: 'Failed to create snapshot',
      });
    }
  }

  private async handleRequestHistory(
    socket: Socket,
    data: { documentId: string; limit?: number },
  ): Promise<void> {
    const { documentStore, logger } = this.deps;
    const { documentId } = data;
    const requested = Math.floor(Number(data.limit) || 20);
    const limit = Math.min(Math.max(requested, 1), MAX_HISTORY_LIMIT);

    try {
      const snapshots = await documentStore.getSnapshots(documentId, limit);
      socket.emit('document-history', { documentId, snapshots });
    } catch (err) {
      logger.error({ err, documentId }, 'get_history_failed');
      socket.emit('history-error', {
        documentId,
        error: 'Failed to retrieve history',
      });
    }
  }

  private handleDisconnect(socket: Socket, reason: string): void {
    const { io, awareness, presenceHandler, metrics, logger } = this.deps;

    metrics.activeConnections.dec();
    logger.info({ socketId: socket.id, reason }, 'client_disconnected');

    this.untrackSocket(socket.id);
    this.socketUpdateLimiter.reset(socket.id);
    this.socketSnapshotLimiter.reset(socket.id);
    const mapping = awareness.removeUser(socket.id);
    if (mapping) {
      const room = `doc:${mapping.documentId}`;
      socket.to(room).emit('user-left', {
        socketId: socket.id,
        userId: mapping.userId,
      });
      presenceHandler.broadcastPresenceUpdate(io, mapping.documentId);

      // Clean up empty documents
      const userCount = awareness.getDocumentUserCount(mapping.documentId);
      if (userCount === 0) {
        this.persistAndCleanupDocument(mapping.documentId);
      }
    }
  }

  async persistAndCleanupDocument(documentId: string): Promise<void> {
    // Guard against concurrent cleanup calls for the same document
    if (this.cleaningUp.has(documentId)) return;
    this.cleaningUp.add(documentId);

    const { documentStore, metrics, logger } = this.deps;
    const doc = this.documents.get(documentId);
    if (!doc) {
      this.cleaningUp.delete(documentId);
      return;
    }

    const pending = this.persistTimers.get(documentId);
    if (pending) {
      clearTimeout(pending);
      this.persistTimers.delete(documentId);
    }

    try {
      const state = Y.encodeStateAsUpdate(doc);
      this.dirty.delete(documentId);
      await documentStore.saveDocumentState(
        documentId,
        Buffer.from(state),
        this.lastModifiedBy.get(documentId),
      );
      logger.info({ documentId }, 'document_persisted_on_cleanup');
      // Re-check if users have re-joined during the async persistence
      if (this.deps.awareness.getDocumentUserCount(documentId) === 0) {
        this.documents.delete(documentId);
        this.budget.release(this.budgetKey(documentId));
        this.dirty.delete(documentId);
        this.changedSinceSnapshot.delete(documentId);
        this.lastModifiedBy.delete(documentId);
        metrics.activeRooms.dec();
        logger.debug({ documentId }, 'document_removed_from_memory');
      }
    } catch (err) {
      this.dirty.add(documentId);
      logger.error({ err, documentId }, 'document_persist_on_cleanup_failed');
      // Keep document in memory so the periodic persistence loop can retry
    } finally {
      this.cleaningUp.delete(documentId);
    }
  }

  private async getOrCreateDoc(documentId: string): Promise<Y.Doc> {
    const existing = this.documents.get(documentId);
    if (existing) return existing;

    const pending = this.documentInitPromises.get(documentId);
    if (pending) return pending;

    const { documentStore, metrics } = this.deps;
    const initPromise = (async () => {
      try {
        const doc = new Y.Doc();
        const savedState = await documentStore.getDocumentState(documentId);
        const size = savedState?.length ?? 0;
        if (size > this.limits.maxDocumentBytes) {
          throw new DocumentLimitError('Document exceeds size limit');
        }
        if (this.budget.wouldExceed(this.budgetKey(documentId), size)) {
          throw new DocumentLimitError('Server document capacity reached');
        }
        if (savedState) {
          Y.applyUpdate(doc, savedState);
        }
        this.budget.set(this.budgetKey(documentId), size);
        this.documents.set(documentId, doc);
        metrics.activeRooms.inc();
        return doc;
      } finally {
        this.documentInitPromises.delete(documentId);
      }
    })();

    this.documentInitPromises.set(documentId, initPromise);
    return initPromise;
  }

  private startPersistenceLoop(): void {
    // Safety net for debounced writes that failed; only dirty documents are written
    this.persistTimer = setInterval(async () => {
      for (const documentId of Array.from(this.dirty)) {
        await this.persistDocument(documentId, 'periodic_save');
      }
    }, this.deps.persistIntervalMs);
  }

  private startSnapshotLoop(): void {
    const { documentStore, logger } = this.deps;

    // Only documents edited since their last auto-snapshot get a new one
    this.snapshotTimer = setInterval(async () => {
      for (const documentId of Array.from(this.changedSinceSnapshot)) {
        const doc = this.documents.get(documentId);
        this.changedSinceSnapshot.delete(documentId);
        if (!doc) continue;
        try {
          const state = Y.encodeStateAsUpdate(doc);
          await documentStore.createSnapshot(
            documentId,
            Buffer.from(state),
            'system',
            'auto-snapshot',
          );
        } catch (err) {
          logger.error({ err, documentId }, 'periodic_snapshot_failed');
        }
      }
    }, this.deps.snapshotIntervalMs);
  }
}

/** Convenience function matching the original API for backward compatibility */
export function setupCollaborationHandlers(
  io: SocketIOServer,
  documentStore: DocumentStore,
  awareness: AwarenessService,
  presenceHandler: PresenceHandler,
  metrics: MetricsCollector,
  logger: Logger,
  persistIntervalMs = 30000,
  snapshotIntervalMs = 300000,
  limits?: Partial<CollaborationLimits>,
  memoryBudget?: DocumentMemoryBudget,
): CollaborationManager {
  const manager = new CollaborationManager({
    io,
    documentStore,
    awareness,
    presenceHandler,
    metrics,
    logger,
    persistIntervalMs,
    snapshotIntervalMs,
    limits,
    memoryBudget,
  });
  manager.start();
  return manager;
}
