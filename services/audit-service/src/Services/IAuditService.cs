using OtterWorks.AuditService.Models;

namespace OtterWorks.AuditService.Services;

public interface IAuditService
{
    Task<AuditEventResponse> RecordEventAsync(AuditEventRequest request);
    Task<AuditEventResponse?> GetEventAsync(string id);
    Task<AuditEventPage> QueryEventsAsync(string? userId, string? action, string? resourceType, string? resourceId, DateTime? from, DateTime? to, int page, int pageSize);
    Task<UserActivityReport> GetUserActivityReportAsync(string userId, string period);
    Task<ResourceHistory> GetResourceHistoryAsync(string resourceId, int page = 1, int pageSize = 20);
    Task<ComplianceReport> GetComplianceReportAsync(string period);
    Task<ExportResult> ExportAsync(DateTime from, DateTime to, string format);
    Task<ArchiveResult> ArchiveOldEventsAsync();
}
