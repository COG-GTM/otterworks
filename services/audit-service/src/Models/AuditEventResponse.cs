using System.Text.Json;
using OtterWorks.AuditService.Services;

namespace OtterWorks.AuditService.Models;

public sealed class AuditEventResponse
{
    public string Id { get; set; } = string.Empty;
    public string UserId { get; set; } = string.Empty;
    public string Action { get; set; } = string.Empty;
    public string ResourceType { get; set; } = string.Empty;
    public string ResourceId { get; set; } = string.Empty;
    public Dictionary<string, string>? Details { get; set; }
    public string? IpAddress { get; set; }
    public string? UserAgent { get; set; }
    public DateTime Timestamp { get; set; }
    public string? WorkspaceId { get; set; }
    public JsonElement? OldValue { get; set; }
    public JsonElement? NewValue { get; set; }

    public static AuditEventResponse FromEntity(AuditEvent entity) => new()
    {
        Id = entity.Id,
        UserId = entity.UserId,
        Action = entity.Action,
        ResourceType = entity.ResourceType,
        ResourceId = entity.ResourceId,
        Details = entity.Details,
        IpAddress = entity.IpAddress,
        UserAgent = entity.UserAgent,
        Timestamp = entity.Timestamp,
        WorkspaceId = entity.WorkspaceId,
        OldValue = entity.OldValue,
        NewValue = entity.NewValue,
    };
}
