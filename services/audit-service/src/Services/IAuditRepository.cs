namespace OtterWorks.AuditService.Services;

public interface IAuditRepository
{
    Task SaveEventAsync(AuditEvent auditEvent);
    Task<AuditEvent?> GetEventAsync(string id);
    Task<AuditEventPage> QueryEventsAsync(string? userId, string? action, string? resourceType, string? resourceId, DateTime? from, DateTime? to, int page, int pageSize);
    IAsyncEnumerable<AuditEvent> StreamUserEventsAsync(string userId, DateTime from, DateTime to, CancellationToken cancellationToken = default);
    Task<AuditEventPage> GetResourceHistoryAsync(string resourceId, int limit);
    IAsyncEnumerable<AuditEvent> StreamEventsByDateRangeAsync(DateTime from, DateTime to, CancellationToken cancellationToken = default);
    Task<int> DeleteEventsAsync(IEnumerable<string> eventIds);
}
