using OtterWorks.AuditService.Config;

namespace AuditService.Tests;

public class AwsSettingsTests
{
    [Fact]
    public void AwsSettings_ShouldExposeLocalStackDefaults()
    {
        var settings = new AwsSettings();

        Assert.Equal("us-east-1", settings.Region);
        Assert.Null(settings.EndpointUrl);
        Assert.Equal("otterworks-audit-events", settings.DynamoDbTable);
        Assert.Equal("otterworks-audit-archive", settings.S3ArchiveBucket);
        Assert.Null(settings.SnsTopicArn);
        Assert.Equal(90, settings.ArchiveAfterDays);
    }

    [Fact]
    public void AwsSettings_ShouldRoundTripOverrides()
    {
        var settings = new AwsSettings
        {
            Region = "eu-west-1",
            EndpointUrl = "http://localstack:4566",
            DynamoDbTable = "custom-events",
            S3ArchiveBucket = "custom-archive",
            SnsTopicArn = "arn:aws:sns:eu-west-1:000000000000:audit",
            ArchiveAfterDays = 30,
        };

        Assert.Equal("eu-west-1", settings.Region);
        Assert.Equal("http://localstack:4566", settings.EndpointUrl);
        Assert.Equal("custom-events", settings.DynamoDbTable);
        Assert.Equal("custom-archive", settings.S3ArchiveBucket);
        Assert.Equal("arn:aws:sns:eu-west-1:000000000000:audit", settings.SnsTopicArn);
        Assert.Equal(30, settings.ArchiveAfterDays);
    }
}
