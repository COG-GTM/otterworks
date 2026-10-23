namespace OtterWorks.AuditService.Models;

public sealed class ArchiveResult
{
    public int ArchivedCount { get; set; }
    public string S3Location { get; set; } = string.Empty;
    public DateTime ArchivedBefore { get; set; }
    public bool HasMore { get; set; }
    public string StorageClass { get; set; } = "GLACIER";
}
