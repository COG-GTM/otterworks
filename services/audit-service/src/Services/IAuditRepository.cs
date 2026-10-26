namespace OtterWorks.AuditService.Services;

public interface IAuditRepository
{
    Task SaveEventAsync(AuditEvent auditEvent);
    Task<AuditEvent?> GetEventAsync(string id);
    Task<AuditEventPage> QueryEventsAsync(string? userId, string? action, string? resourceType, string? resourceId, DateTime? from, DateTime? to, int page, int pageSize, string? cursor);
    Task<AuditEventBatch> GetUserEventsAsync(string userId, DateTime from, DateTime to, int maxEvents);
    Task<AuditEventBatch> GetEventsByDateRangeAsync(DateTime from, DateTime to, int maxEvents);
    Task<int> DeleteEventsAsync(IEnumerable<string> eventIds);
}
