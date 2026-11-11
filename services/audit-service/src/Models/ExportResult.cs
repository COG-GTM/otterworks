namespace OtterWorks.AuditService.Models;

public sealed class ExportResult
{
    public string Format { get; set; } = "json";
    public int EventCount { get; set; }
    public string DownloadUrl { get; set; } = string.Empty;
    public DateTime From { get; set; }
    public DateTime To { get; set; }
    public bool Truncated { get; set; }
}
