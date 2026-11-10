namespace OtterWorks.AuditService.Models;

public sealed class AuditEventRequest
{
    public string UserId { get; set; } = string.Empty;
    public string? ActorEmail { get; set; }
    public string? ActorType { get; set; }
    public string? TenantId { get; set; }
    public string Action { get; set; } = string.Empty;
    public string ResourceType { get; set; } = string.Empty;
    public string ResourceId { get; set; } = string.Empty;
    public string? Outcome { get; set; }
    public Dictionary<string, string>? Details { get; set; }
    public string? IpAddress { get; set; }

    // v2 alias of IpAddress; IpAddress wins when both are sent.
    public string? SourceIp { get; set; }
    public string? UserAgent { get; set; }
    public string? RequestId { get; set; }
    public string? ServiceName { get; set; }
    public DateTime? Timestamp { get; set; }
}
