using Microsoft.Extensions.Configuration;
using OtterWorks.AuditService.Config;

namespace AuditService.Tests;

public class AwsSettingsTests
{
    [Fact]
    public void Defaults_ShouldMatchTheDeployedConfiguration()
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
    public void Bind_ShouldOverrideEveryDefaultFromConfiguration()
    {
        var configuration = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["Aws:Region"] = "eu-west-1",
                ["Aws:EndpointUrl"] = "http://localstack:4566",
                ["Aws:DynamoDbTable"] = "custom-events",
                ["Aws:S3ArchiveBucket"] = "custom-archive",
                ["Aws:SnsTopicArn"] = "arn:aws:sns:eu-west-1:000000000000:audit",
                ["Aws:ArchiveAfterDays"] = "7",
            })
            .Build();

        var settings = configuration.GetSection("Aws").Get<AwsSettings>();

        Assert.NotNull(settings);
        Assert.Equal("eu-west-1", settings.Region);
        Assert.Equal("http://localstack:4566", settings.EndpointUrl);
        Assert.Equal("custom-events", settings.DynamoDbTable);
        Assert.Equal("custom-archive", settings.S3ArchiveBucket);
        Assert.Equal("arn:aws:sns:eu-west-1:000000000000:audit", settings.SnsTopicArn);
        Assert.Equal(7, settings.ArchiveAfterDays);
    }
}
