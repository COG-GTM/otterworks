namespace OtterWorks.AuditService.Models;

public sealed class ResourceHistory
{
    public string ResourceId { get; set; } = string.Empty;
    public int TotalEvents { get; set; }
    public List<AuditEventResponse> Events { get; set; } = new();
    public string? NextCursor { get; set; }
    public bool HasMore => NextCursor is not null;
}
