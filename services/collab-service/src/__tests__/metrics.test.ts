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

  it('registers every collab metric on its own registry', async () => {
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

  it('renders counter increments with their labels', async () => {
    metrics.messagesTotal.inc({ type: 'join-document' });
    metrics.messagesTotal.inc({ type: 'join-document' });
    metrics.commentAnnotationsTotal.inc({ action: 'add' });
    metrics.connectionErrors.inc({ reason: 'join_failed' });

    const output = await metrics.getMetrics();

    expect(output).toContain('collab_messages_total{type="join-document"} 2');
    expect(output).toContain('collab_comment_annotations_total{action="add"} 1');
    expect(output).toContain('collab_connection_errors_total{reason="join_failed"} 1');
  });

  it('tracks gauges up and down', async () => {
    metrics.activeConnections.inc();
    metrics.activeConnections.inc();
    metrics.activeConnections.dec();
    metrics.activeRooms.inc();

    const output = await metrics.getMetrics();

    expect(output).toContain('collab_active_connections 1');
    expect(output).toContain('collab_active_rooms 1');
  });

  it('records histogram observations with their operation label', async () => {
    metrics.documentSyncDuration.observe(0.002);
    metrics.persistenceDuration.observe({ operation: 'save_state' }, 0.02);

    const output = await metrics.getMetrics();

    expect(output).toContain('collab_document_sync_duration_seconds_count 1');
    expect(output).toContain(
      'collab_persistence_duration_seconds_count{operation="save_state"} 1',
    );
  });

  it('also collects default process metrics', async () => {
    const output = await metrics.getMetrics();

    expect(output).toContain('process_start_time_seconds');
    expect(output).toContain('nodejs_eventloop_lag_seconds');
  });
});
