namespace OtterWorks.AuditService.Services;

public class AuditEvent
{
    public string Id { get; set; } = string.Empty;
    public string UserId { get; set; } = string.Empty;
    public string? ActorEmail { get; set; }
    public string? ActorType { get; set; } // user, admin, service, anonymous
    public string? TenantId { get; set; }
    public string Action { get; set; } = string.Empty; // dot-namespaced, e.g. auth.login.success, share.create, export, delete
    public string ResourceType { get; set; } = string.Empty; // file, document, folder, user, role, share_link, export_archive
    public string ResourceId { get; set; } = string.Empty;
    public string? Outcome { get; set; } // success, failure, denied
    public Dictionary<string, string>? Details { get; set; }
    public string? IpAddress { get; set; }
    public string? UserAgent { get; set; }
    public string? RequestId { get; set; }
    public string? ServiceName { get; set; }
    public DateTime Timestamp { get; set; }
}

public class AuditEventPage
{
    public List<AuditEvent> Events { get; set; } = new();
    public int Total { get; set; }
    public int Page { get; set; }
    public int PageSize { get; set; }
}

public sealed class AuditEventQuery
{
    public string? UserId { get; set; }
    public string? Action { get; set; }
    public string? ResourceType { get; set; }
    public string? ResourceId { get; set; }
    public string? Outcome { get; set; }
    public string? ServiceName { get; set; }
    public string? TenantId { get; set; }
    public DateTime? From { get; set; }
    public DateTime? To { get; set; }
    public int Page { get; set; } = 1;
    public int PageSize { get; set; } = 20;
}
