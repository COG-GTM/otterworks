namespace OtterWorks.AuditService.Config;

public class AwsSettings
{
    public string Region { get; set; } = "us-east-1";
    public string? EndpointUrl { get; set; }
    public string DynamoDbTable { get; set; } = "otterworks-audit-events";
    public string S3ArchiveBucket { get; set; } = "otterworks-audit-archive";
    public string? SnsTopicArn { get; set; }
    public int ArchiveAfterDays { get; set; } = 90;

    // Tenant that owns this deployment. Stamped on every saved event and used to
    // scope archival on a table shared between tenants.
    public string? TenantId { get; set; }
}
