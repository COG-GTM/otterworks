import { MetricsCollector } from '../metrics';

describe('MetricsCollector', () => {
  it('exposes custom collab metrics in Prometheus text format', async () => {
    const metrics = new MetricsCollector();
    metrics.activeConnections.inc();
    metrics.messagesTotal.inc({ type: 'join-document' });
    metrics.persistenceOperations.inc({ operation: 'save_state', status: 'success' });

    const output = await metrics.getMetrics();
    expect(output).toContain('collab_active_connections 1');
    expect(output).toContain('collab_messages_total{type="join-document"} 1');
    expect(output).toContain(
      'collab_persistence_operations_total{operation="save_state",status="success"} 1',
    );
    expect(output).toContain('process_cpu_user_seconds_total');
  });

  it('returns the Prometheus content type', () => {
    const metrics = new MetricsCollector();
    expect(metrics.getContentType()).toMatch(/^text\/plain/);
  });

  it('uses an isolated registry per instance', async () => {
    const a = new MetricsCollector();
    const b = new MetricsCollector();
    a.activeRooms.inc(3);
    expect(await b.getMetrics()).toContain('collab_active_rooms 0');
  });
});
