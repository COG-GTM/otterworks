namespace OtterWorks.AuditService.Services;

public interface IAuditRepository
{
    Task SaveEventAsync(AuditEvent auditEvent);
    Task<AuditEvent?> GetEventAsync(string id);
    Task<AuditEventPage> QueryEventsAsync(string? userId, string? action, string? resourceType, string? resourceId, DateTime? from, DateTime? to, string? cursor, int pageSize);
    Task<AuditEventBatch> GetUserEventsAsync(string userId, DateTime from, DateTime to, int maxItems);
    Task<AuditEventBatch> GetResourceHistoryAsync(string resourceId, DateTime from, DateTime to, int maxItems);
    Task<AuditEventBatch> GetEventsByDateRangeAsync(DateTime from, DateTime to, int maxItems, bool oldestFirst = false);
    Task<int> DeleteEventsAsync(IEnumerable<string> eventIds);
}
