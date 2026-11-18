using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Amazon.DynamoDBv2;
using Amazon.DynamoDBv2.Model;
using Amazon.S3;
using Amazon.SimpleNotificationService;
using Amazon.SQS;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Diagnostics.HealthChecks;
using Microsoft.Extensions.Hosting;
using Moq;
using OtterWorks.AuditService.Models;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

public class AuditApiFactory : WebApplicationFactory<Program>
{
    public Mock<IAuditService> AuditService { get; } = new();
    public Mock<IAmazonDynamoDB> DynamoDb { get; } = new();

    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        builder.ConfigureTestServices(services =>
        {
            services.RemoveAll<IHostedService>();
            services.AddSingleton(AuditService.Object);
            services.AddSingleton(DynamoDb.Object);
        });
    }
}

internal static class ServiceCollectionTestExtensions
{
    public static void RemoveAll<T>(this IServiceCollection services)
    {
        foreach (var d in services.Where(d => d.ServiceType == typeof(T)).ToList())
            services.Remove(d);
    }
}

public class AuditApiTests : IClassFixture<AuditApiFactory>
{
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);
    private readonly AuditApiFactory _factory;
    private readonly HttpClient _client;

    public AuditApiTests(AuditApiFactory factory)
    {
        _factory = factory;
        _factory.AuditService.Reset();
        _factory.DynamoDb.Reset();
        _client = factory.CreateClient();
    }

    [Fact]
    public async Task RecordEvent_Valid_Returns201WithLocation()
    {
        _factory.AuditService.Setup(s => s.RecordEventAsync(It.IsAny<AuditEventRequest>()))
            .ReturnsAsync((AuditEventRequest r) => new AuditEventResponse { Id = "evt-1", UserId = r.UserId, Action = r.Action });

        var resp = await _client.PostAsJsonAsync("/api/v1/audit/events",
            new { userId = "u1", action = "create", resourceType = "file", resourceId = "f1" });

        Assert.Equal(HttpStatusCode.Created, resp.StatusCode);
        Assert.Equal("/api/v1/audit/events/evt-1", resp.Headers.Location!.OriginalString);
        var body = await resp.Content.ReadFromJsonAsync<AuditEventResponse>(Json);
        Assert.Equal("u1", body!.UserId);
    }

    [Theory]
    [InlineData("", "create", "file", "f1")]
    [InlineData("u1", " ", "file", "f1")]
    [InlineData("u1", "create", "", "f1")]
    [InlineData("u1", "create", "file", "")]
    public async Task RecordEvent_MissingRequiredField_Returns400(string userId, string action, string resourceType, string resourceId)
    {
        var resp = await _client.PostAsJsonAsync("/api/v1/audit/events",
            new { userId, action, resourceType, resourceId });

        Assert.Equal(HttpStatusCode.BadRequest, resp.StatusCode);
        Assert.Contains("required", await resp.Content.ReadAsStringAsync());
        _factory.AuditService.Verify(s => s.RecordEventAsync(It.IsAny<AuditEventRequest>()), Times.Never);
    }

    [Fact]
    public async Task QueryEvents_MapsQueryAndClampsPageSize()
    {
        _factory.AuditService.Setup(s => s.QueryEventsAsync(It.IsAny<string?>(), It.IsAny<string?>(), It.IsAny<string?>(), It.IsAny<string?>(),
                It.IsAny<DateTime?>(), It.IsAny<DateTime?>(), It.IsAny<int>(), It.IsAny<int>()))
            .ReturnsAsync(new AuditEventPage { Total = 0, Page = 3, PageSize = 100 });

        var resp = await _client.GetAsync("/api/v1/audit/events?user_id=u1&action=read&resource=f1&resource_type=file&from=2026-01-01T00:00:00Z&to=2026-02-01T00:00:00Z&page=3&size=500");

        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);
        _factory.AuditService.Verify(s => s.QueryEventsAsync("u1", "read", "file", "f1",
            It.Is<DateTime?>(d => d.HasValue && d.Value.ToUniversalTime() == new DateTime(2026, 1, 1, 0, 0, 0, DateTimeKind.Utc)),
            It.Is<DateTime?>(d => d.HasValue), 3, 100), Times.Once);
    }

    [Fact]
    public async Task QueryEvents_Defaults()
    {
        _factory.AuditService.Setup(s => s.QueryEventsAsync(null, null, null, null, null, null, 1, 20))
            .ReturnsAsync(new AuditEventPage());

        var resp = await _client.GetAsync("/api/v1/audit/events?size=0");
        var resp2 = await _client.GetAsync("/api/v1/audit/events");

        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);
        Assert.Equal(HttpStatusCode.OK, resp2.StatusCode);
        _factory.AuditService.Verify(s => s.QueryEventsAsync(null, null, null, null, null, null, 1, 1), Times.Once);
        _factory.AuditService.Verify(s => s.QueryEventsAsync(null, null, null, null, null, null, 1, 20), Times.Once);
    }

    [Fact]
    public async Task GetEvent_FoundAndNotFound()
    {
        _factory.AuditService.Setup(s => s.GetEventAsync("e1")).ReturnsAsync(new AuditEventResponse { Id = "e1" });
        _factory.AuditService.Setup(s => s.GetEventAsync("missing")).ReturnsAsync((AuditEventResponse?)null);

        var found = await _client.GetAsync("/api/v1/audit/events/e1");
        var missing = await _client.GetAsync("/api/v1/audit/events/missing");

        Assert.Equal(HttpStatusCode.OK, found.StatusCode);
        Assert.Equal("e1", (await found.Content.ReadFromJsonAsync<AuditEventResponse>(Json))!.Id);
        Assert.Equal(HttpStatusCode.NotFound, missing.StatusCode);
    }

    [Fact]
    public async Task UserActivityReport_DefaultsAndExplicitPeriod()
    {
        _factory.AuditService.Setup(s => s.GetUserActivityReportAsync("u1", It.IsAny<string>()))
            .ReturnsAsync((string u, string p) => new UserActivityReport { UserId = u, Period = p });

        var d = await _client.GetFromJsonAsync<UserActivityReport>("/api/v1/audit/reports/user/u1", Json);
        var w = await _client.GetFromJsonAsync<UserActivityReport>("/api/v1/audit/reports/user/u1?period=7d", Json);

        Assert.Equal("30d", d!.Period);
        Assert.Equal("7d", w!.Period);
    }

    [Fact]
    public async Task ResourceHistory_ReturnsHistory()
    {
        _factory.AuditService.Setup(s => s.GetResourceHistoryAsync("f1"))
            .ReturnsAsync(new ResourceHistory { ResourceId = "f1", TotalEvents = 2 });

        var h = await _client.GetFromJsonAsync<ResourceHistory>("/api/v1/audit/resources/f1/history", Json);

        Assert.Equal(2, h!.TotalEvents);
    }

    [Fact]
    public async Task ComplianceReport_DefaultsAndExplicitPeriod()
    {
        _factory.AuditService.Setup(s => s.GetComplianceReportAsync(It.IsAny<string>()))
            .ReturnsAsync((string p) => new ComplianceReport { Period = p });

        var d = await _client.GetFromJsonAsync<ComplianceReport>("/api/v1/audit/reports/compliance", Json);
        var y = await _client.GetFromJsonAsync<ComplianceReport>("/api/v1/audit/reports/compliance?period=year", Json);

        Assert.Equal("30d", d!.Period);
        Assert.Equal("year", y!.Period);
    }

    [Fact]
    public async Task Export_DefaultsToJsonAndLast30Days()
    {
        DateTime from = default, to = default;
        _factory.AuditService.Setup(s => s.ExportAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>(), "json"))
            .Callback<DateTime, DateTime, string>((f, t, _) => { from = f; to = t; })
            .ReturnsAsync(new ExportResult { Format = "json" });

        var resp = await _client.GetAsync("/api/v1/audit/export");

        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);
        Assert.Equal(30, Math.Round((to - from).TotalDays));
    }

    [Fact]
    public async Task Export_CsvWithExplicitRange()
    {
        _factory.AuditService.Setup(s => s.ExportAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>(), "CSV"))
            .ReturnsAsync(new ExportResult { Format = "CSV", EventCount = 4 });

        var r = await _client.GetFromJsonAsync<ExportResult>("/api/v1/audit/export?format=CSV&from=2026-01-01&to=2026-01-31", Json);

        Assert.Equal(4, r!.EventCount);
        _factory.AuditService.Verify(s => s.ExportAsync(new DateTime(2026, 1, 1), new DateTime(2026, 1, 31), "CSV"), Times.Once);
    }

    [Fact]
    public async Task Export_UnsupportedFormat_Returns400()
    {
        var resp = await _client.GetAsync("/api/v1/audit/export?format=xml");

        Assert.Equal(HttpStatusCode.BadRequest, resp.StatusCode);
        _factory.AuditService.Verify(s => s.ExportAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>(), It.IsAny<string>()), Times.Never);
    }

    [Fact]
    public async Task Archive_ReturnsResult()
    {
        _factory.AuditService.Setup(s => s.ArchiveOldEventsAsync())
            .ReturnsAsync(new ArchiveResult { ArchivedCount = 7, S3Location = "s3://b/k" });

        var resp = await _client.PostAsync("/api/v1/audit/archive", null);

        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);
        Assert.Equal(7, (await resp.Content.ReadFromJsonAsync<ArchiveResult>(Json))!.ArchivedCount);
    }

    [Fact]
    public async Task UnhandledServiceException_Returns500Json()
    {
        _factory.AuditService.Setup(s => s.GetResourceHistoryAsync("boom")).ThrowsAsync(new InvalidOperationException("secret detail"));

        var resp = await _client.GetAsync("/api/v1/audit/resources/boom/history");

        Assert.Equal(HttpStatusCode.InternalServerError, resp.StatusCode);
        var body = await resp.Content.ReadAsStringAsync();
        Assert.Contains("An internal server error occurred.", body);
        Assert.DoesNotContain("secret detail", body);
    }

    [Fact]
    public async Task Health_WhenDynamoReachable_Returns200()
    {
        _factory.DynamoDb.Setup(d => d.ListTablesAsync(It.IsAny<CancellationToken>())).ReturnsAsync(new ListTablesResponse());

        var resp = await _client.GetAsync("/health");

        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);
        Assert.Contains("\"healthy\"", await resp.Content.ReadAsStringAsync());
    }

    [Fact]
    public async Task Health_WhenDynamoUnreachable_Returns503()
    {
        _factory.DynamoDb.Setup(d => d.ListTablesAsync(It.IsAny<CancellationToken>())).ThrowsAsync(new AmazonDynamoDBException("down"));

        var resp = await _client.GetAsync("/health");

        Assert.Equal(HttpStatusCode.ServiceUnavailable, resp.StatusCode);
        Assert.Contains("\"unhealthy\"", await resp.Content.ReadAsStringAsync());
    }

    [Fact]
    public async Task Metrics_ReturnsPrometheusText()
    {
        await _client.GetAsync("/api/v1/audit/events/none");
        var resp = await _client.GetAsync("/metrics");

        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);
        Assert.StartsWith("text/plain", resp.Content.Headers.ContentType!.ToString());
        Assert.Contains("http_requests_received_total", await resp.Content.ReadAsStringAsync());
    }

    [Fact]
    public async Task DynamoDbHealthCheck_ReportsHealthyAndUnhealthy()
    {
        var dynamo = new Mock<IAmazonDynamoDB>();
        dynamo.SetupSequence(d => d.ListTablesAsync(It.IsAny<CancellationToken>()))
            .ReturnsAsync(new ListTablesResponse())
            .ThrowsAsync(new AmazonDynamoDBException("down"));
        var check = new DynamoDbHealthCheck(dynamo.Object);

        var healthy = await check.CheckHealthAsync(new HealthCheckContext());
        var unhealthy = await check.CheckHealthAsync(new HealthCheckContext());

        Assert.Equal(HealthStatus.Healthy, healthy.Status);
        Assert.Equal(HealthStatus.Unhealthy, unhealthy.Status);
        Assert.IsType<AmazonDynamoDBException>(unhealthy.Exception);
    }
}

public class AwsClientRegistrationTests
{
    private sealed class ClientFactory : WebApplicationFactory<Program>
    {
        private readonly string? _endpoint;

        public ClientFactory(string? endpoint) => _endpoint = endpoint;

        protected override void ConfigureWebHost(IWebHostBuilder builder)
        {
            if (_endpoint is not null)
                builder.UseSetting("Aws:EndpointUrl", _endpoint);
            builder.UseSetting("Aws:Region", "eu-west-1");
            builder.ConfigureTestServices(services => services.RemoveAll<IHostedService>());
        }
    }

    static AwsClientRegistrationTests()
    {
        if (string.IsNullOrEmpty(Environment.GetEnvironmentVariable("AWS_ACCESS_KEY_ID")))
        {
            Environment.SetEnvironmentVariable("AWS_ACCESS_KEY_ID", "test");
            Environment.SetEnvironmentVariable("AWS_SECRET_ACCESS_KEY", "test");
        }
    }

    [Fact]
    public void WithEndpointOverride_PointsAllClientsAtEndpoint()
    {
        using var factory = new ClientFactory("http://localstack:4566");
        var sp = factory.Services;

        var dynamo = (AmazonDynamoDBClient)sp.GetRequiredService<IAmazonDynamoDB>();
        var s3 = (AmazonS3Client)sp.GetRequiredService<IAmazonS3>();
        var sqs = (AmazonSQSClient)sp.GetRequiredService<IAmazonSQS>();
        var sns = (AmazonSimpleNotificationServiceClient)sp.GetRequiredService<IAmazonSimpleNotificationService>();

        Assert.StartsWith("http://localstack:4566", dynamo.Config.ServiceURL);
        Assert.StartsWith("http://localstack:4566", s3.Config.ServiceURL);
        Assert.True(((AmazonS3Config)s3.Config).ForcePathStyle);
        Assert.StartsWith("http://localstack:4566", sqs.Config.ServiceURL);
        Assert.StartsWith("http://localstack:4566", sns.Config.ServiceURL);
        Assert.IsType<DynamoDbAuditRepository>(sp.GetRequiredService<IAuditRepository>());
        Assert.IsType<S3AuditArchiver>(sp.GetRequiredService<IAuditArchiver>());
    }

    [Fact]
    public void WithoutEndpoint_UsesConfiguredRegion()
    {
        using var factory = new ClientFactory(null);
        var sp = factory.Services;

        var dynamo = (AmazonDynamoDBClient)sp.GetRequiredService<IAmazonDynamoDB>();
        var s3 = (AmazonS3Client)sp.GetRequiredService<IAmazonS3>();
        var sqs = (AmazonSQSClient)sp.GetRequiredService<IAmazonSQS>();
        var sns = (AmazonSimpleNotificationServiceClient)sp.GetRequiredService<IAmazonSimpleNotificationService>();

        Assert.Null(dynamo.Config.ServiceURL);
        Assert.Equal(Amazon.RegionEndpoint.EUWest1, dynamo.Config.RegionEndpoint);
        Assert.Equal(Amazon.RegionEndpoint.EUWest1, s3.Config.RegionEndpoint);
        Assert.Equal(Amazon.RegionEndpoint.EUWest1, sqs.Config.RegionEndpoint);
        Assert.Equal(Amazon.RegionEndpoint.EUWest1, sns.Config.RegionEndpoint);
    }

    [Fact]
    public void RegistersSnsConsumerAsHostedService()
    {
        using var factory = new WebApplicationFactory<Program>().WithWebHostBuilder(b =>
            b.ConfigureTestServices(s => s.AddSingleton(new Mock<IAmazonSQS>().Object)));
        var hosted = factory.Services.GetServices<IHostedService>();

        Assert.Contains(hosted, h => h is SnsConsumer);
    }
}
