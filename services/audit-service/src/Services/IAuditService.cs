using OtterWorks.AuditService.Models;

namespace OtterWorks.AuditService.Services;

public interface IAuditService
{
    Task<AuditEventResponse> RecordEventAsync(AuditEventRequest request);
    Task<AuditEventResponse?> GetEventAsync(string id);
    Task<AuditEventPage> QueryEventsAsync(AuditEventQuery query);
    Task<UserActivityReport> GetUserActivityReportAsync(string userId, string period);
    Task<ResourceHistory> GetResourceHistoryAsync(string resourceId, string? cursor, int pageSize);
    Task<ComplianceReport> GetComplianceReportAsync(string period);
    Task<ExportResult> ExportAsync(DateTime from, DateTime to, string format);
    Task<ArchiveResult> ArchiveOldEventsAsync();
}
