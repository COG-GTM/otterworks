namespace OtterWorks.AuditService.Models;

public sealed class UserActivityReport
{
    public string UserId { get; set; } = string.Empty;
    public string Period { get; set; } = string.Empty;
    public int TotalEvents { get; set; }
    public Dictionary<string, int> ActionCounts { get; set; } = new();
    public Dictionary<string, int> ResourceTypeCounts { get; set; } = new();
    public DateTime? FirstActivity { get; set; }
    public DateTime? LastActivity { get; set; }
    public List<AuditEventResponse> RecentEvents { get; set; } = new();
    public bool Truncated { get; set; }
}
