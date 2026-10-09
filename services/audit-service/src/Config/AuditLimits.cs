namespace OtterWorks.AuditService.Config;

public class AuditLimits
{
    public int ScanPageSize { get; set; } = 500;
    public int MaxQueryWindow { get; set; } = 10_000;
    public int MaxResourceHistoryEvents { get; set; } = 500;
    public int MaxReportEvents { get; set; } = 50_000;
    public int MaxExportRangeDays { get; set; } = 31;
    public int MaxExportEvents { get; set; } = 50_000;
    public int ArchiveBatchSize { get; set; } = 5_000;
    public int MaxFieldLength { get; set; } = 256;
    public int MaxIpAddressLength { get; set; } = 64;
    public int MaxUserAgentLength { get; set; } = 1_024;
    public int MaxDetailsEntries { get; set; } = 32;
    public int MaxDetailKeyLength { get; set; } = 128;
    public int MaxDetailValueLength { get; set; } = 1_024;
    public int MaxDetailsTotalLength { get; set; } = 8_192;
    public long MaxRequestBodyBytes { get; set; } = 64 * 1_024;
}
