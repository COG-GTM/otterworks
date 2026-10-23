namespace OtterWorks.AuditService.Config;

public class AwsSettings
{
    public string Region { get; set; } = "us-east-1";
    public string? EndpointUrl { get; set; }
    public string DynamoDbTable { get; set; } = "otterworks-audit-events";
    public string DynamoDbUserIndex { get; set; } = "user-index";
    public string DynamoDbTimestampIndex { get; set; } = "timestamp-index";

    // Optional GSI keyed on resource_id/timestamp. When unset, resource history walks the
    // timestamp index with a filter, bounded by MaxItemsEvaluatedPerRequest.
    public string? DynamoDbResourceIndex { get; set; }

    public string S3ArchiveBucket { get; set; } = "otterworks-audit-archive";
    public string? SnsTopicArn { get; set; }
    public int ArchiveAfterDays { get; set; } = 90;

    public int MaxItemsEvaluatedPerRequest { get; set; } = 1000;
    public int MaxEventsPerReport { get; set; } = 10000;
    public int MaxQueryWindowDays { get; set; } = 366;
    public int DefaultQueryLookbackDays { get; set; } = 90;
}
