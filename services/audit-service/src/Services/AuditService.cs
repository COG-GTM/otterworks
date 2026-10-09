using Microsoft.Extensions.Options;
using OtterWorks.AuditService.Config;
using OtterWorks.AuditService.Models;

namespace OtterWorks.AuditService.Services;

public class AuditService : IAuditService
{
    private const int RecentEventCount = 10;

    private readonly IAuditRepository _repository;
    private readonly IAuditArchiver _archiver;
    private readonly AwsSettings _settings;
    private readonly AuditLimits _limits;
    private readonly ILogger<AuditService> _logger;

    public AuditService(
        IAuditRepository repository,
        IAuditArchiver archiver,
        IOptions<AwsSettings> settings,
        IOptions<AuditLimits> limits,
        ILogger<AuditService> logger)
    {
        _repository = repository;
        _archiver = archiver;
        _settings = settings.Value;
        _limits = limits.Value;
        _logger = logger;
    }

    public async Task<AuditEventResponse> RecordEventAsync(AuditEventRequest request)
    {
        var auditEvent = new AuditEvent
        {
            Id = Guid.NewGuid().ToString(),
            UserId = request.UserId,
            Action = request.Action,
            ResourceType = request.ResourceType,
            ResourceId = request.ResourceId,
            Details = request.Details,
            IpAddress = request.IpAddress,
            UserAgent = request.UserAgent,
            Timestamp = DateTime.UtcNow,
        };

        await _repository.SaveEventAsync(auditEvent);
        _logger.LogInformation("Audit event recorded: {Action} on {ResourceType}/{ResourceId} by {UserId}",
            auditEvent.Action, auditEvent.ResourceType, auditEvent.ResourceId, auditEvent.UserId);

        return AuditEventResponse.FromEntity(auditEvent);
    }

    public async Task<AuditEventResponse?> GetEventAsync(string id)
    {
        var auditEvent = await _repository.GetEventAsync(id);
        return auditEvent is not null ? AuditEventResponse.FromEntity(auditEvent) : null;
    }

    public async Task<AuditEventPage> QueryEventsAsync(
        string? userId, string? action, string? resourceType, string? resourceId,
        DateTime? from, DateTime? to, int page, int pageSize)
    {
        return await _repository.QueryEventsAsync(userId, action, resourceType, resourceId, from, to, page, pageSize);
    }

    public async Task<UserActivityReport> GetUserActivityReportAsync(string userId, string period)
    {
        var (from, to) = ParsePeriod(period);
        var report = new UserActivityReport
        {
            UserId = userId,
            Period = period,
        };
        var recent = new List<AuditEvent>();

        await foreach (var e in _repository.StreamUserEventsAsync(userId, from, to))
        {
            if (report.TotalEvents >= _limits.MaxReportEvents)
            {
                report.Truncated = true;
                break;
            }

            report.TotalEvents++;
            Increment(report.ActionCounts, e.Action);
            Increment(report.ResourceTypeCounts, e.ResourceType);
            if (report.FirstActivity is null || e.Timestamp < report.FirstActivity)
                report.FirstActivity = e.Timestamp;
            if (report.LastActivity is null || e.Timestamp > report.LastActivity)
                report.LastActivity = e.Timestamp;

            recent.Add(e);
            if (recent.Count > RecentEventCount * 4)
                recent = recent.OrderByDescending(r => r.Timestamp).Take(RecentEventCount).ToList();
        }

        report.RecentEvents = recent
            .OrderByDescending(e => e.Timestamp)
            .Take(RecentEventCount)
            .Select(AuditEventResponse.FromEntity)
            .ToList();

        _logger.LogInformation("Generated user activity report for {UserId} ({Period}): {TotalEvents} events",
            userId, period, report.TotalEvents);
        return report;
    }

    public async Task<ResourceHistory> GetResourceHistoryAsync(string resourceId)
    {
        var history = await _repository.GetResourceHistoryAsync(resourceId, _limits.MaxResourceHistoryEvents);

        return new ResourceHistory
        {
            ResourceId = resourceId,
            TotalEvents = history.Total,
            Events = history.Events.Select(AuditEventResponse.FromEntity).ToList(),
        };
    }

    public async Task<ComplianceReport> GetComplianceReportAsync(string period)
    {
        var (from, to) = ParsePeriod(period);
        var report = new ComplianceReport { Period = period };
        var userEventCounts = new Dictionary<string, int>();

        await foreach (var e in _repository.StreamEventsByDateRangeAsync(from, to))
        {
            if (report.TotalEvents >= _limits.MaxReportEvents)
            {
                report.Truncated = true;
                break;
            }

            report.TotalEvents++;
            Increment(userEventCounts, e.UserId);
            Increment(report.ActionBreakdown, e.Action);
            Increment(report.ResourceTypeBreakdown, e.ResourceType);
        }

        var averageEvents = userEventCounts.Count > 0
            ? userEventCounts.Values.Average()
            : 0;

        var suspiciousThreshold = Math.Max(averageEvents * 3, 100);

        report.SuspiciousActivities = userEventCounts
            .Where(kvp => kvp.Value > suspiciousThreshold)
            .Select(kvp => new SuspiciousActivity
            {
                UserId = kvp.Key,
                Reason = $"Unusually high activity: {kvp.Value} events (threshold: {suspiciousThreshold:F0})",
                EventCount = kvp.Value,
            })
            .ToList();
        report.UniqueUsers = userEventCounts.Count;
        report.GeneratedAt = DateTime.UtcNow;

        _logger.LogInformation("Generated compliance report ({Period}): {TotalEvents} events, {UniqueUsers} users, {SuspiciousCount} suspicious",
            period, report.TotalEvents, report.UniqueUsers, report.SuspiciousActivities.Count);
        return report;
    }

    public async Task<ExportResult> ExportAsync(DateTime from, DateTime to, string format)
    {
        return await _archiver.ExportAsync(from, to, format);
    }

    public async Task<ArchiveResult> ArchiveOldEventsAsync()
    {
        var cutoff = DateTime.UtcNow.AddDays(-_settings.ArchiveAfterDays);
        return await _archiver.ArchiveOldEventsAsync(cutoff);
    }

    private static void Increment(Dictionary<string, int> counts, string key) =>
        counts[key] = counts.TryGetValue(key, out var count) ? count + 1 : 1;

    private static (DateTime from, DateTime to) ParsePeriod(string period)
    {
        var to = DateTime.UtcNow;
        var from = period.ToLowerInvariant() switch
        {
            "day" or "24h" => to.AddDays(-1),
            "week" or "7d" => to.AddDays(-7),
            "month" or "30d" => to.AddDays(-30),
            "quarter" or "90d" => to.AddDays(-90),
            "year" or "365d" => to.AddDays(-365),
            _ => to.AddDays(-30),
        };
        return (from, to);
    }
}
