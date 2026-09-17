import { MetricsCollector } from '../metrics';

describe('MetricsCollector', () => {
  let metrics: MetricsCollector;

  beforeEach(() => {
    metrics = new MetricsCollector();
  });

  afterEach(() => {
    metrics.registry.clear();
  });

  it('exposes the Prometheus text content type', () => {
    expect(metrics.getContentType()).toContain('text/plain');
  });

  it('renders default process metrics alongside the collab metrics', async () => {
    const output = await metrics.getMetrics();

    expect(output).toContain('process_cpu_user_seconds_total');
    expect(output).toContain('collab_active_connections');
    expect(output).toContain('collab_active_rooms');
  });

  it('records gauge, counter and histogram values', async () => {
    metrics.activeConnections.inc();
    metrics.activeConnections.inc();
    metrics.activeConnections.dec();
    metrics.activeRooms.inc();
    metrics.messagesTotal.inc({ type: 'join-document' });
    metrics.documentUpdatesTotal.inc();
    metrics.presenceUpdatesTotal.inc();
    metrics.commentAnnotationsTotal.inc({ action: 'add' });
    metrics.connectionErrors.inc({ reason: 'join_failed' });
    metrics.persistenceOperations.inc({ operation: 'save_state', status: 'success' });
    metrics.documentSyncDuration.observe(0.01);
    metrics.persistenceDuration.observe({ operation: 'save_state' }, 0.02);

    const output = await metrics.getMetrics();

    expect(output).toContain('collab_active_connections 1');
    expect(output).toContain('collab_active_rooms 1');
    expect(output).toContain('collab_messages_total{type="join-document"} 1');
    expect(output).toContain('collab_document_updates_total 1');
    expect(output).toContain('collab_presence_updates_total 1');
    expect(output).toContain('collab_comment_annotations_total{action="add"} 1');
    expect(output).toContain('collab_connection_errors_total{reason="join_failed"} 1');
    expect(output).toContain(
      'collab_persistence_operations_total{operation="save_state",status="success"} 1',
    );
    expect(output).toContain('collab_document_sync_duration_seconds_count 1');
    expect(output).toContain(
      'collab_persistence_duration_seconds_count{operation="save_state"} 1',
    );
  });

  it('keeps each collector on its own registry', async () => {
    const other = new MetricsCollector();
    metrics.documentUpdatesTotal.inc();

    const output = await other.getMetrics();

    expect(output).toContain('collab_document_updates_total 0');
    other.registry.clear();
  });
});
