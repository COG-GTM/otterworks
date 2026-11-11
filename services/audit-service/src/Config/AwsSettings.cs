namespace OtterWorks.AuditService.Config;

public class AwsSettings
{
    public string Region { get; set; } = "us-east-1";
    public string? EndpointUrl { get; set; }
    public string DynamoDbTable { get; set; } = "otterworks-audit-events";
    public string S3ArchiveBucket { get; set; } = "otterworks-audit-archive";

    // Prepended to every archive/export key. Tenants on the shared bucket get
    // "tenants/<id>/", the only prefix their IAM role can write. Empty for the
    // golden app.
    public string S3KeyPrefix { get; set; } = string.Empty;
    public string? SnsTopicArn { get; set; }
    public int ArchiveAfterDays { get; set; } = 90;
}
