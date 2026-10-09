namespace OtterWorks.AuditService.Config;

public class AwsSettings
{
    public string Region { get; set; } = "us-east-1";
    public string? EndpointUrl { get; set; }
    public string DynamoDbTable { get; set; } = "otterworks-audit-events";
    public string S3ArchiveBucket { get; set; } = "otterworks-audit-archive";

    // Prefix for archive object keys. Tenant deployments set tenants/<tenant-id>/
    // because the archive bucket is shared and a tenant role only grants that prefix.
    public string S3KeyPrefix { get; set; } = string.Empty;
    public string? SnsTopicArn { get; set; }
    public int ArchiveAfterDays { get; set; } = 90;
}
