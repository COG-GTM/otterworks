using System.Text.Json;

namespace OtterWorks.AuditService.Models;

public sealed class AuditEventRequest
{
    public string UserId { get; set; } = string.Empty;
    public string Action { get; set; } = string.Empty;
    public string ResourceType { get; set; } = string.Empty;
    public string ResourceId { get; set; } = string.Empty;
    public Dictionary<string, string>? Details { get; set; }
    public string? IpAddress { get; set; }
    public string? UserAgent { get; set; }
    public string? WorkspaceId { get; set; }
    public JsonElement? OldValue { get; set; }
    public JsonElement? NewValue { get; set; }
}
