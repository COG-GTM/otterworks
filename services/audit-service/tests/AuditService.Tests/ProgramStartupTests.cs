using System.Net;
using Amazon.DynamoDBv2;
using Amazon.DynamoDBv2.Model;
using Amazon.S3;
using Amazon.SimpleNotificationService;
using Amazon.SQS;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using Microsoft.Extensions.Diagnostics.HealthChecks;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Options;
using Moq;
using OtterWorks.AuditService.Config;

namespace AuditService.Tests;

public class ProgramStartupTests
{
    static ProgramStartupTests()
    {
        // The DI graph builds real AWS SDK clients, whose constructors resolve credentials.
        // Nothing in these tests talks to AWS; the values only have to exist.
        Environment.SetEnvironmentVariable("AWS_ACCESS_KEY_ID", "test-access-key");
        Environment.SetEnvironmentVariable("AWS_SECRET_ACCESS_KEY", "test-secret-key");
    }

    [Fact]
    public async Task HealthEndpoint_ReturnsHealthy_WhenDynamoDbIsReachable()
    {
        var dynamoDb = new Mock<IAmazonDynamoDB>();
        dynamoDb
            .Setup(d => d.ListTablesAsync(It.IsAny<CancellationToken>()))
            .ReturnsAsync(new ListTablesResponse());

        await using var factory = CreateFactory(services =>
        {
            services.RemoveAll<IAmazonDynamoDB>();
            services.AddSingleton(dynamoDb.Object);
        });
        using var client = factory.CreateClient();

        var response = await client.GetAsync("/health");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Contains("\"status\":\"healthy\"", await response.Content.ReadAsStringAsync());
    }

    [Fact]
    public async Task HealthEndpoint_Returns503_WhenDynamoDbIsUnreachable()
    {
        var dynamoDb = new Mock<IAmazonDynamoDB>();
        dynamoDb
            .Setup(d => d.ListTablesAsync(It.IsAny<CancellationToken>()))
            .ThrowsAsync(new AmazonDynamoDBException("no connection"));

        await using var factory = CreateFactory(services =>
        {
            services.RemoveAll<IAmazonDynamoDB>();
            services.AddSingleton(dynamoDb.Object);
        });
        using var client = factory.CreateClient();

        var response = await client.GetAsync("/health");

        Assert.Equal(HttpStatusCode.ServiceUnavailable, response.StatusCode);
        Assert.Contains("\"status\":\"unhealthy\"", await response.Content.ReadAsStringAsync());
    }

    [Fact]
    public async Task MetricsEndpoint_ReturnsPrometheusText()
    {
        await using var factory = CreateFactory();
        using var client = factory.CreateClient();

        var response = await client.GetAsync("/metrics");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal("text/plain", response.Content.Headers.ContentType?.MediaType);
        Assert.Contains("# TYPE", await response.Content.ReadAsStringAsync());
    }

    [Fact]
    public async Task AwsClients_UseRegionEndpoint_WhenNoEndpointUrlIsConfigured()
    {
        await using var factory = CreateFactory();

        var dynamoDb = (AmazonDynamoDBClient)factory.Services.GetRequiredService<IAmazonDynamoDB>();
        var s3 = (AmazonS3Client)factory.Services.GetRequiredService<IAmazonS3>();
        var sqs = (AmazonSQSClient)factory.Services.GetRequiredService<IAmazonSQS>();
        var sns = (AmazonSimpleNotificationServiceClient)
            factory.Services.GetRequiredService<IAmazonSimpleNotificationService>();

        Assert.Equal("us-east-1", dynamoDb.Config.RegionEndpoint.SystemName);
        Assert.Null(((AmazonDynamoDBConfig)dynamoDb.Config).ServiceURL);
        Assert.False(((AmazonS3Config)s3.Config).ForcePathStyle);
        Assert.Equal("us-east-1", s3.Config.RegionEndpoint.SystemName);
        Assert.Equal("us-east-1", sqs.Config.RegionEndpoint.SystemName);
        Assert.Equal("us-east-1", sns.Config.RegionEndpoint.SystemName);
    }

    [Fact]
    public async Task AwsClients_PointAtLocalEndpoint_WhenEndpointUrlIsConfigured()
    {
        const string endpoint = "http://localstack:4566/";
        await using var factory = CreateFactory(settings: new Dictionary<string, string>
        {
            ["Aws:EndpointUrl"] = endpoint,
            ["Aws:SnsTopicArn"] = "arn:aws:sns:us-east-1:000000000000:audit-events",
        });

        var dynamoDb = (AmazonDynamoDBClient)factory.Services.GetRequiredService<IAmazonDynamoDB>();
        var s3 = (AmazonS3Client)factory.Services.GetRequiredService<IAmazonS3>();
        var sqs = (AmazonSQSClient)factory.Services.GetRequiredService<IAmazonSQS>();
        var sns = (AmazonSimpleNotificationServiceClient)
            factory.Services.GetRequiredService<IAmazonSimpleNotificationService>();
        var settings = factory.Services.GetRequiredService<IOptions<AwsSettings>>().Value;

        Assert.Equal(endpoint, dynamoDb.Config.ServiceURL);
        Assert.Equal(endpoint, s3.Config.ServiceURL);
        Assert.True(((AmazonS3Config)s3.Config).ForcePathStyle);
        Assert.Equal(endpoint, sqs.Config.ServiceURL);
        Assert.Equal(endpoint, sns.Config.ServiceURL);
        Assert.Equal(endpoint, settings.EndpointUrl);
        Assert.Equal("arn:aws:sns:us-east-1:000000000000:audit-events", settings.SnsTopicArn);
    }

    [Fact]
    public async Task DynamoDbHealthCheck_ReportsHealthy_WhenListTablesSucceeds()
    {
        var dynamoDb = new Mock<IAmazonDynamoDB>();
        dynamoDb
            .Setup(d => d.ListTablesAsync(It.IsAny<CancellationToken>()))
            .ReturnsAsync(new ListTablesResponse());

        var result = await new DynamoDbHealthCheck(dynamoDb.Object)
            .CheckHealthAsync(new HealthCheckContext());

        Assert.Equal(HealthStatus.Healthy, result.Status);
        Assert.Equal("DynamoDB is reachable", result.Description);
    }

    [Fact]
    public async Task DynamoDbHealthCheck_ReportsUnhealthy_WhenListTablesThrows()
    {
        var failure = new AmazonDynamoDBException("down");
        var dynamoDb = new Mock<IAmazonDynamoDB>();
        dynamoDb
            .Setup(d => d.ListTablesAsync(It.IsAny<CancellationToken>()))
            .ThrowsAsync(failure);

        var result = await new DynamoDbHealthCheck(dynamoDb.Object)
            .CheckHealthAsync(new HealthCheckContext());

        Assert.Equal(HealthStatus.Unhealthy, result.Status);
        Assert.Equal("DynamoDB is unreachable", result.Description);
        Assert.Same(failure, result.Exception);
    }

    private static WebApplicationFactory<Program> CreateFactory(
        Action<IServiceCollection>? configureServices = null,
        Dictionary<string, string>? settings = null) =>
        new WebApplicationFactory<Program>().WithWebHostBuilder(builder =>
        {
            foreach (var (key, value) in settings ?? new Dictionary<string, string>())
                builder.UseSetting(key, value);

            builder.ConfigureServices(services =>
            {
                services.RemoveAll<IHostedService>();
                configureServices?.Invoke(services);
            });
        });
}
