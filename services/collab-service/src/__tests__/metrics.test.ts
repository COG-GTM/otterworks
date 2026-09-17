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

  it('renders every collab metric in the exposition format', async () => {
    const output = await metrics.getMetrics();

    for (const name of [
      'collab_active_connections',
      'collab_active_rooms',
      'collab_messages_total',
      'collab_document_updates_total',
      'collab_document_sync_duration_seconds',
      'collab_presence_updates_total',
      'collab_comment_annotations_total',
      'collab_connection_errors_total',
      'collab_persistence_operations_total',
      'collab_persistence_duration_seconds',
    ]) {
      expect(output).toContain(name);
    }
  });

  it('renders recorded values for counters, gauges and histograms', async () => {
    metrics.activeConnections.inc();
    metrics.activeConnections.inc();
    metrics.activeConnections.dec();
    metrics.activeRooms.set(3);
    metrics.messagesTotal.inc({ type: 'join-document' });
    metrics.documentUpdatesTotal.inc(4);
    metrics.documentSyncDuration.observe(0.02);
    metrics.presenceUpdatesTotal.inc();
    metrics.commentAnnotationsTotal.inc({ action: 'add' });
    metrics.connectionErrors.inc({ reason: 'join_failed' });
    metrics.persistenceOperations.inc({ operation: 'save_state', status: 'success' });
    metrics.persistenceDuration.observe({ operation: 'save_state' }, 0.5);

    const output = await metrics.getMetrics();

    expect(output).toContain('collab_active_connections 1');
    expect(output).toContain('collab_active_rooms 3');
    expect(output).toContain('collab_messages_total{type="join-document"} 1');
    expect(output).toContain('collab_document_updates_total 4');
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

  it('keeps each collector isolated in its own registry', async () => {
    const other = new MetricsCollector();
    metrics.documentUpdatesTotal.inc(7);

    const output = await other.getMetrics();

    expect(output).toContain('collab_document_updates_total 0');
    other.registry.clear();
  });
});
