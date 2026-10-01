using Microsoft.Extensions.Configuration;
using OtterWorks.AuditService.Config;

namespace AuditService.Tests;

public class AwsSettingsTests
{
    [Fact]
    public void AwsSettings_ShouldExposeGoldenDefaults()
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
    public void AwsSettings_ShouldBindFromConfigurationSection()
    {
        var configuration = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?>
            {
                ["Aws:Region"] = "eu-west-1",
                ["Aws:EndpointUrl"] = "http://localstack:4566",
                ["Aws:DynamoDbTable"] = "tenant-audit-events",
                ["Aws:S3ArchiveBucket"] = "tenant-audit-archive",
                ["Aws:SnsTopicArn"] = "arn:aws:sns:eu-west-1:1234:audit",
                ["Aws:ArchiveAfterDays"] = "7",
            })
            .Build();

        var settings = configuration.GetSection("Aws").Get<AwsSettings>();

        Assert.NotNull(settings);
        Assert.Equal("eu-west-1", settings!.Region);
        Assert.Equal("http://localstack:4566", settings.EndpointUrl);
        Assert.Equal("tenant-audit-events", settings.DynamoDbTable);
        Assert.Equal("tenant-audit-archive", settings.S3ArchiveBucket);
        Assert.Equal("arn:aws:sns:eu-west-1:1234:audit", settings.SnsTopicArn);
        Assert.Equal(7, settings.ArchiveAfterDays);
    }
}
