using Microsoft.Extensions.Options;
using OtterWorks.AuditService.Config;
using OtterWorks.AuditService.Models;

namespace OtterWorks.AuditService.Services;

public class AuditService : IAuditService
{
    private readonly IAuditRepository _repository;
    private readonly IAuditArchiver _archiver;
    private readonly AwsSettings _settings;
    private readonly ILogger<AuditService> _logger;

    public AuditService(
        IAuditRepository repository,
        IAuditArchiver archiver,
        IOptions<AwsSettings> settings,
        ILogger<AuditService> logger)
    {
        _repository = repository;
        _archiver = archiver;
        _settings = settings.Value;
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
        DateTime? from, DateTime? to, int page, int pageSize, string? cursor = null)
    {
        return await _repository.QueryEventsAsync(userId, action, resourceType, resourceId, from, to, page, pageSize, cursor);
    }

    public async Task<UserActivityReport> GetUserActivityReportAsync(string userId, string period)
    {
        var (from, to) = ParsePeriod(period);
        var batch = await _repository.GetUserEventsAsync(userId, from, to, AuditQueryLimits.MaxReportEvents);
        var filtered = batch.Events;

        var report = new UserActivityReport
        {
            UserId = userId,
            Period = period,
            TotalEvents = filtered.Count,
            ActionCounts = filtered.GroupBy(e => e.Action)
                .ToDictionary(g => g.Key, g => g.Count()),
            ResourceTypeCounts = filtered.GroupBy(e => e.ResourceType)
                .ToDictionary(g => g.Key, g => g.Count()),
            FirstActivity = filtered.MinBy(e => e.Timestamp)?.Timestamp,
            LastActivity = filtered.MaxBy(e => e.Timestamp)?.Timestamp,
            RecentEvents = filtered
                .OrderByDescending(e => e.Timestamp)
                .Take(10)
                .Select(AuditEventResponse.FromEntity)
                .ToList(),
            Truncated = batch.Truncated,
        };

        _logger.LogInformation("Generated user activity report for {UserId} ({Period}): {TotalEvents} events",
            userId, period, report.TotalEvents);
        return report;
    }

    public async Task<ResourceHistory> GetResourceHistoryAsync(
        string resourceId, DateTime? from = null, DateTime? to = null, int pageSize = 100, string? cursor = null)
    {
        var page = await _repository.QueryEventsAsync(null, null, null, resourceId, from, to, 1, pageSize, cursor);

        return new ResourceHistory
        {
            ResourceId = resourceId,
            TotalEvents = page.Events.Count,
            Events = page.Events.Select(AuditEventResponse.FromEntity).ToList(),
            NextCursor = page.NextCursor,
            HasMore = page.HasMore,
        };
    }

    public async Task<ComplianceReport> GetComplianceReportAsync(string period)
    {
        var (from, to) = ParsePeriod(period);
        var batch = await _repository.GetEventsByDateRangeAsync(from, to, AuditQueryLimits.MaxReportEvents);
        var events = batch.Events;

        var userEventCounts = events.GroupBy(e => e.UserId)
            .ToDictionary(g => g.Key, g => g.Count());

        var averageEvents = userEventCounts.Count > 0
            ? userEventCounts.Values.Average()
            : 0;

        var suspiciousThreshold = Math.Max(averageEvents * 3, 100);

        var suspicious = userEventCounts
            .Where(kvp => kvp.Value > suspiciousThreshold)
            .Select(kvp => new SuspiciousActivity
            {
                UserId = kvp.Key,
                Reason = $"Unusually high activity: {kvp.Value} events (threshold: {suspiciousThreshold:F0})",
                EventCount = kvp.Value,
            })
            .ToList();

        var report = new ComplianceReport
        {
            Period = period,
            TotalEvents = events.Count,
            UniqueUsers = userEventCounts.Count,
            ActionBreakdown = events.GroupBy(e => e.Action)
                .ToDictionary(g => g.Key, g => g.Count()),
            ResourceTypeBreakdown = events.GroupBy(e => e.ResourceType)
                .ToDictionary(g => g.Key, g => g.Count()),
            SuspiciousActivities = suspicious,
            GeneratedAt = DateTime.UtcNow,
            Truncated = batch.Truncated,
        };

        _logger.LogInformation("Generated compliance report ({Period}): {TotalEvents} events, {UniqueUsers} users, {SuspiciousCount} suspicious",
            period, report.TotalEvents, report.UniqueUsers, suspicious.Count);
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
