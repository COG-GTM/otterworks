namespace OtterWorks.AuditService.Services;

public interface IAuditRepository
{
    Task SaveEventAsync(AuditEvent auditEvent);
    Task<AuditEvent?> GetEventAsync(string id);
    Task<AuditEventPage> QueryEventsAsync(AuditEventQuery query);
    Task<List<AuditEvent>> GetAllUserEventsAsync(string userId);
    Task<List<AuditEvent>> GetResourceHistoryAsync(string resourceId);
    Task<List<AuditEvent>> GetEventsByDateRangeAsync(DateTime from, DateTime to);
    Task<int> DeleteEventsAsync(IEnumerable<string> eventIds);
}
