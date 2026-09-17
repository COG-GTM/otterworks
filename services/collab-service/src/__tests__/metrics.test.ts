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

  it('renders registered collab metrics in the exposition output', async () => {
    metrics.activeConnections.inc();
    metrics.activeRooms.inc(2);
    metrics.messagesTotal.inc({ type: 'join-document' });
    metrics.documentUpdatesTotal.inc();
    metrics.presenceUpdatesTotal.inc();

    const output = await metrics.getMetrics();

    expect(output).toContain('collab_active_connections 1');
    expect(output).toContain('collab_active_rooms 2');
    expect(output).toContain('collab_messages_total{type="join-document"} 1');
    expect(output).toContain('collab_document_updates_total 1');
    expect(output).toContain('collab_presence_updates_total 1');
  });

  it('includes default process metrics in its own registry', async () => {
    const output = await metrics.getMetrics();

    expect(output).toContain('process_cpu_user_seconds_total');
  });

  it('tracks labelled counters independently', async () => {
    metrics.commentAnnotationsTotal.inc({ action: 'add' });
    metrics.commentAnnotationsTotal.inc({ action: 'add' });
    metrics.commentAnnotationsTotal.inc({ action: 'delete' });
    metrics.connectionErrors.inc({ reason: 'join_failed' });
    metrics.persistenceOperations.inc({ operation: 'save_state', status: 'error' });

    const output = await metrics.getMetrics();

    expect(output).toContain('collab_comment_annotations_total{action="add"} 2');
    expect(output).toContain('collab_comment_annotations_total{action="delete"} 1');
    expect(output).toContain('collab_connection_errors_total{reason="join_failed"} 1');
    expect(output).toContain(
      'collab_persistence_operations_total{operation="save_state",status="error"} 1',
    );
  });

  it('records observations into the duration histograms', async () => {
    metrics.documentSyncDuration.observe(0.02);
    metrics.persistenceDuration.observe({ operation: 'periodic_save' }, 0.2);

    const output = await metrics.getMetrics();

    expect(output).toContain('collab_document_sync_duration_seconds_count 1');
    expect(output).toContain('collab_document_sync_duration_seconds_sum 0.02');
    expect(output).toContain(
      'collab_persistence_duration_seconds_count{operation="periodic_save"} 1',
    );
  });

  it('gives each collector an isolated registry', async () => {
    const other = new MetricsCollector();
    metrics.activeConnections.inc(5);

    const output = await other.getMetrics();

    expect(output).toContain('collab_active_connections 0');
    other.registry.clear();
  });
});
