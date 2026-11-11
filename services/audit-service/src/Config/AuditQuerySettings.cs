namespace OtterWorks.AuditService.Config;

public class AuditQuerySettings
{
    public string UserIndexName { get; set; } = "user-index";
    public string DateIndexName { get; set; } = "timestamp-index";
    public int MaxQueryCallsPerPage { get; set; } = 10;
    public int MaxQueryCallsPerBatch { get; set; } = 500;
    public int DefaultQueryWindowDays { get; set; } = 30;
    public int MaxQueryRangeDays { get; set; } = 366;
    public int MaxExportRangeDays { get; set; } = 31;
    public int MaxReportEvents { get; set; } = 5000;
    public int ResourceHistoryDays { get; set; } = 90;
    public int ArchiveLookbackDays { get; set; } = 365;
    public int ArchiveBatchSize { get; set; } = 5000;
}
