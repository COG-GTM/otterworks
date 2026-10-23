namespace OtterWorks.AuditService.Services;

public interface IAuditRepository
{
    Task SaveEventAsync(AuditEvent auditEvent);
    Task<AuditEvent?> GetEventAsync(string id);
    Task<AuditEventPage> QueryEventsAsync(AuditEventQuery query);
    Task<AuditEventPage> GetUserEventsAsync(string userId, DateTime from, DateTime to, int maxEvents);
    Task<AuditEventPage> GetResourceHistoryAsync(string resourceId, string? cursor, int pageSize);
    Task<AuditEventPage> GetEventsByDateRangeAsync(DateTime from, DateTime to, int maxEvents);
    Task<int> DeleteEventsAsync(IEnumerable<string> eventIds);
}
