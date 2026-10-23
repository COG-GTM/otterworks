namespace OtterWorks.AuditService.Config;

public class AwsSettings
{
    public string Region { get; set; } = "us-east-1";
    public string? EndpointUrl { get; set; }
    public string DynamoDbTable { get; set; } = "otterworks-audit-events";
    public string S3ArchiveBucket { get; set; } = "otterworks-audit-archive";
    public string? TenantId { get; set; }
    public string? SnsTopicArn { get; set; }
    public int ArchiveAfterDays { get; set; } = 90;

    // The audit table is shared between tenants, so an unscoped deployment would read
    // every tenant's untagged records; refuse to start instead.
    public void EnsureTenantConfigured()
    {
        if (string.IsNullOrWhiteSpace(TenantId))
            throw new InvalidOperationException("Aws:TenantId must be configured; the audit table is shared between tenants.");
    }
}
