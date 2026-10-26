using OtterWorks.AuditService.Models;

namespace OtterWorks.AuditService.Services;

public interface IAuditService
{
    Task<AuditEventResponse> RecordEventAsync(AuditEventRequest request);
    Task<AuditEventResponse?> GetEventAsync(string id);
    Task<AuditEventPage> QueryEventsAsync(string? userId, string? action, string? resourceType, string? resourceId, DateTime? from, DateTime? to, int page, int pageSize, string? cursor = null);
    Task<UserActivityReport> GetUserActivityReportAsync(string userId, string period);
    Task<ResourceHistory> GetResourceHistoryAsync(string resourceId, DateTime? from = null, DateTime? to = null, int pageSize = 100, string? cursor = null);
    Task<ComplianceReport> GetComplianceReportAsync(string period);
    Task<ExportResult> ExportAsync(DateTime from, DateTime to, string format);
    Task<ArchiveResult> ArchiveOldEventsAsync();
}
