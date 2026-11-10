using Microsoft.Extensions.Options;
using OtterWorks.AuditService.Auth;
using Prometheus;

namespace OtterWorks.AuditService.Services;

public sealed class SelfAuditOptions
{
    public TimeSpan Timeout { get; set; } = TimeSpan.FromSeconds(2);
    public int MaxAttempts { get; set; } = 2;
}

/// <summary>Marks an endpoint whose calls (including denied ones) audit-service audits itself.</summary>
public sealed record SelfAuditMetadata(string Action, string ResourceType, string? ResourceRouteValue = null);

/// <summary>
/// Records audit-service's own sensitive operations (export, archive, admin report reads).
/// Never throws: a slow or failing store only logs and increments audit_emit_failures_total.
/// </summary>
public sealed class SelfAuditor
{
    public const string ServiceName = "audit-service";

    public static readonly Counter EmitFailures = Metrics.CreateCounter(
        "audit_emit_failures_total",
        "Self-audit events that could not be stored after the bounded retry.",
        new CounterConfiguration { LabelNames = new[] { "action" } });

    private readonly IAuditRepository _repository;
    private readonly SelfAuditOptions _options;
    private readonly ILogger<SelfAuditor> _logger;

    public SelfAuditor(IAuditRepository repository, IOptions<SelfAuditOptions> options, ILogger<SelfAuditor> logger)
    {
        _repository = repository;
        _options = options.Value;
        _logger = logger;
    }

    public async Task RecordAsync(
        HttpContext context,
        string action,
        string resourceType,
        string resourceId,
        string outcome,
        Dictionary<string, string>? details = null)
    {
        var auditEvent = BuildEvent(context, action, resourceType, resourceId, outcome, details);
        var attempts = Math.Max(1, _options.MaxAttempts);

        for (var attempt = 1; attempt <= attempts; attempt++)
        {
            try
            {
                await _repository.SaveEventAsync(auditEvent).WaitAsync(_options.Timeout);
                return;
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Self-audit emit failed for {Action} (attempt {Attempt}/{Attempts})",
                    action, attempt, attempts);
            }
        }

        EmitFailures.WithLabels(action).Inc();
        _logger.LogError("Dropped self-audit event {Action} {Outcome} on {ResourceType}/{ResourceId} by {UserId}",
            action, outcome, resourceType, resourceId, auditEvent.UserId);
    }

    public static AuditEvent BuildEvent(
        HttpContext context,
        string action,
        string resourceType,
        string resourceId,
        string outcome,
        Dictionary<string, string>? details)
    {
        var user = context.User;
        var authenticated = user.Identity?.IsAuthenticated == true;
        var userId = authenticated ? user.FindFirst("sub")?.Value ?? user.FindFirst("user_id")?.Value : null;
        var request = context.Request;

        return new AuditEvent
        {
            Id = Guid.NewGuid().ToString(),
            UserId = string.IsNullOrEmpty(userId) ? "anonymous" : userId,
            ActorEmail = authenticated ? user.FindFirst("email")?.Value : null,
            ActorType = string.IsNullOrEmpty(userId) ? "anonymous" : AuditAuth.IsAdmin(user) ? "admin" : "user",
            TenantId = NullIfEmpty(request.Headers["X-Tenant-ID"].ToString()),
            Action = action,
            ResourceType = resourceType,
            ResourceId = resourceId,
            Outcome = outcome,
            Details = details,
            IpAddress = ClientIp.Resolve(context),
            UserAgent = NullIfEmpty(request.Headers.UserAgent.ToString()),
            RequestId = NullIfEmpty(request.Headers["X-Request-ID"].ToString()) ?? context.TraceIdentifier,
            ServiceName = ServiceName,
            Timestamp = DateTime.UtcNow,
        };
    }

    private static string? NullIfEmpty(string? value) => string.IsNullOrWhiteSpace(value) ? null : value;
}

public static class ClientIp
{
    /// <summary>First X-Forwarded-For hop, then X-Real-IP, then the socket address.</summary>
    public static string? Resolve(HttpContext context)
    {
        var forwarded = context.Request.Headers["X-Forwarded-For"].ToString();
        if (!string.IsNullOrWhiteSpace(forwarded))
        {
            var first = forwarded.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).FirstOrDefault();
            if (!string.IsNullOrEmpty(first))
                return first;
        }

        var realIp = context.Request.Headers["X-Real-IP"].ToString();
        if (!string.IsNullOrWhiteSpace(realIp))
            return realIp.Trim();

        return context.Connection.RemoteIpAddress?.ToString();
    }
}
