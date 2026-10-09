namespace OtterWorks.AuditService.Models;

public sealed class ComplianceReport
{
    public string Period { get; set; } = string.Empty;
    public int TotalEvents { get; set; }
    public int UniqueUsers { get; set; }
    public Dictionary<string, int> ActionBreakdown { get; set; } = new();
    public Dictionary<string, int> ResourceTypeBreakdown { get; set; } = new();
    public List<SuspiciousActivity> SuspiciousActivities { get; set; } = new();
    public DateTime GeneratedAt { get; set; }
    public bool Truncated { get; set; }
}

public sealed class SuspiciousActivity
{
    public string UserId { get; set; } = string.Empty;
    public string Reason { get; set; } = string.Empty;
    public int EventCount { get; set; }
}
