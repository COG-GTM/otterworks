using OtterWorks.AuditService.Services;

namespace OtterWorks.AuditService.Models;

public sealed class AuditEventResponse
{
    public string Id { get; set; } = string.Empty;
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
    public string? SourceIp { get; set; }
    public string? UserAgent { get; set; }
    public string? RequestId { get; set; }
    public string? ServiceName { get; set; }
    public DateTime Timestamp { get; set; }

    public static AuditEventResponse FromEntity(AuditEvent entity) => new()
    {
        Id = entity.Id,
        UserId = entity.UserId,
        ActorEmail = entity.ActorEmail,
        ActorType = entity.ActorType,
        TenantId = entity.TenantId,
        Action = entity.Action,
        ResourceType = entity.ResourceType,
        ResourceId = entity.ResourceId,
        Outcome = entity.Outcome,
        Details = entity.Details,
        IpAddress = entity.IpAddress,
        SourceIp = entity.IpAddress,
        UserAgent = entity.UserAgent,
        RequestId = entity.RequestId,
        ServiceName = entity.ServiceName,
        Timestamp = entity.Timestamp,
    };
}
