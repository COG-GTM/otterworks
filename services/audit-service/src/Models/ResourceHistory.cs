namespace OtterWorks.AuditService.Models;

public sealed class ResourceHistory
{
    public string ResourceId { get; set; } = string.Empty;
    public int TotalEvents { get; set; }
    public List<AuditEventResponse> Events { get; set; } = new();
    public bool Truncated { get; set; }
}
