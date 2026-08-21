using System.Net;
using System.Net.Http.Json;
using Amazon.DynamoDBv2;
using Amazon.DynamoDBv2.Model;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using Microsoft.Extensions.Hosting;
using Moq;
using OtterWorks.AuditService.Models;
using OtterWorks.AuditService.Services;
using IAuditService = OtterWorks.AuditService.Services.IAuditService;

namespace AuditService.Tests;

public class AuditControllerTests : IAsyncLifetime
{
    private readonly Mock<IAuditService> _mockAuditService = new();
    private readonly Mock<IAmazonDynamoDB> _mockDynamoDb = new();
    private WebApplicationFactory<Program> _factory = null!;
    private HttpClient _client = null!;

    public Task InitializeAsync()
    {
        _factory = new WebApplicationFactory<Program>()
            .WithWebHostBuilder(builder => builder.ConfigureServices(services =>
            {
                services.RemoveAll<IHostedService>();
                services.RemoveAll<IAuditService>();
                services.RemoveAll<IAmazonDynamoDB>();
                services.AddSingleton(_mockAuditService.Object);
                services.AddSingleton(_mockDynamoDb.Object);
            }));
        _client = _factory.CreateClient();
        return Task.CompletedTask;
    }

    public async Task DisposeAsync()
    {
        _client.Dispose();
        await _factory.DisposeAsync();
    }

    [Fact]
    public async Task RecordEvent_ShouldReturn201WithLocation_WhenRequestIsValid()
    {
        var request = new AuditEventRequest
        {
            UserId = "user-1",
            Action = "read",
            ResourceType = "file",
            ResourceId = "file-1",
        };
        _mockAuditService
            .Setup(s => s.RecordEventAsync(It.IsAny<AuditEventRequest>()))
            .ReturnsAsync(new AuditEventResponse
            {
                Id = "evt-1",
                UserId = "user-1",
                Action = "read",
                ResourceType = "file",
                ResourceId = "file-1",
            });

        var response = await _client.PostAsJsonAsync("/api/v1/audit/events", request);

        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
        Assert.Equal("/api/v1/audit/events/evt-1", response.Headers.Location?.ToString());
        var body = await response.Content.ReadFromJsonAsync<AuditEventResponse>();
        Assert.Equal("evt-1", body!.Id);
        _mockAuditService.Verify(
            s => s.RecordEventAsync(It.Is<AuditEventRequest>(r => r.UserId == "user-1" && r.ResourceId == "file-1")),
            Times.Once);
    }

    [Theory]
    [InlineData("", "read", "file", "file-1")]
    [InlineData("  ", "read", "file", "file-1")]
    [InlineData("user-1", "", "file", "file-1")]
    [InlineData("user-1", "read", "", "file-1")]
    [InlineData("user-1", "read", "file", "")]
    public async Task RecordEvent_ShouldReturn400_WhenRequiredFieldIsMissing(
        string userId, string action, string resourceType, string resourceId)
    {
        var response = await _client.PostAsJsonAsync("/api/v1/audit/events", new AuditEventRequest
        {
            UserId = userId,
            Action = action,
            ResourceType = resourceType,
            ResourceId = resourceId,
        });

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Contains("required", await response.Content.ReadAsStringAsync());
        _mockAuditService.Verify(s => s.RecordEventAsync(It.IsAny<AuditEventRequest>()), Times.Never);
    }

    [Fact]
    public async Task QueryEvents_ShouldUseDefaultPaging_WhenNoParametersSupplied()
    {
        _mockAuditService
            .Setup(s => s.QueryEventsAsync(null, null, null, null, null, null, 1, 20))
            .ReturnsAsync(new AuditEventPage { Total = 0, Page = 1, PageSize = 20 });

        var response = await _client.GetAsync("/api/v1/audit/events");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var page = await response.Content.ReadFromJsonAsync<AuditEventPage>();
        Assert.Equal(20, page!.PageSize);
        _mockAuditService.Verify(s => s.QueryEventsAsync(null, null, null, null, null, null, 1, 20), Times.Once);
    }

    [Fact]
    public async Task QueryEvents_ShouldForwardFilters_WhenParametersSupplied()
    {
        var from = new DateTime(2026, 1, 1, 0, 0, 0, DateTimeKind.Utc);
        var to = new DateTime(2026, 2, 1, 0, 0, 0, DateTimeKind.Utc);
        _mockAuditService
            .Setup(s => s.QueryEventsAsync("user-1", "read", "file", "file-1", It.IsAny<DateTime?>(), It.IsAny<DateTime?>(), 3, 50))
            .ReturnsAsync(new AuditEventPage
            {
                Events = new List<AuditEvent> { new() { Id = "evt-1" } },
                Total = 1,
                Page = 3,
                PageSize = 50,
            });

        var response = await _client.GetAsync(
            $"/api/v1/audit/events?user_id=user-1&action=read&resource_type=file&resource=file-1" +
            $"&from={from:o}&to={to:o}&page=3&size=50");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var page = await response.Content.ReadFromJsonAsync<AuditEventPage>();
        Assert.Equal(1, page!.Total);
        Assert.Equal("evt-1", Assert.Single(page.Events).Id);
    }

    [Theory]
    [InlineData(1000, 100)]
    [InlineData(0, 1)]
    [InlineData(-5, 1)]
    public async Task QueryEvents_ShouldClampPageSize_ToSupportedRange(int requestedSize, int expectedSize)
    {
        _mockAuditService
            .Setup(s => s.QueryEventsAsync(null, null, null, null, null, null, 1, expectedSize))
            .ReturnsAsync(new AuditEventPage { Page = 1, PageSize = expectedSize });

        var response = await _client.GetAsync($"/api/v1/audit/events?size={requestedSize}");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        _mockAuditService.Verify(
            s => s.QueryEventsAsync(null, null, null, null, null, null, 1, expectedSize),
            Times.Once);
    }

    [Fact]
    public async Task GetEvent_ShouldReturn200_WhenEventExists()
    {
        _mockAuditService
            .Setup(s => s.GetEventAsync("evt-1"))
            .ReturnsAsync(new AuditEventResponse { Id = "evt-1", UserId = "user-1" });

        var response = await _client.GetAsync("/api/v1/audit/events/evt-1");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var body = await response.Content.ReadFromJsonAsync<AuditEventResponse>();
        Assert.Equal("user-1", body!.UserId);
    }

    [Fact]
    public async Task GetEvent_ShouldReturn404_WhenEventIsMissing()
    {
        _mockAuditService.Setup(s => s.GetEventAsync("missing")).ReturnsAsync((AuditEventResponse?)null);

        var response = await _client.GetAsync("/api/v1/audit/events/missing");

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
        Assert.Contains("Event not found.", await response.Content.ReadAsStringAsync());
    }

    [Theory]
    [InlineData(null, "30d")]
    [InlineData("7d", "7d")]
    public async Task GetUserActivityReport_ShouldDefaultPeriodTo30d(string? period, string expectedPeriod)
    {
        _mockAuditService
            .Setup(s => s.GetUserActivityReportAsync("user-1", expectedPeriod))
            .ReturnsAsync(new UserActivityReport { UserId = "user-1", Period = expectedPeriod, TotalEvents = 4 });

        var url = period is null
            ? "/api/v1/audit/reports/user/user-1"
            : $"/api/v1/audit/reports/user/user-1?period={period}";
        var response = await _client.GetAsync(url);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var report = await response.Content.ReadFromJsonAsync<UserActivityReport>();
        Assert.Equal(expectedPeriod, report!.Period);
        Assert.Equal(4, report.TotalEvents);
    }

    [Fact]
    public async Task GetResourceHistory_ShouldReturnHistoryForResource()
    {
        _mockAuditService
            .Setup(s => s.GetResourceHistoryAsync("file-1"))
            .ReturnsAsync(new ResourceHistory
            {
                ResourceId = "file-1",
                TotalEvents = 2,
                Events = new List<AuditEventResponse> { new() { Id = "evt-1" }, new() { Id = "evt-2" } },
            });

        var response = await _client.GetAsync("/api/v1/audit/resources/file-1/history");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var history = await response.Content.ReadFromJsonAsync<ResourceHistory>();
        Assert.Equal("file-1", history!.ResourceId);
        Assert.Equal(2, history.TotalEvents);
    }

    [Theory]
    [InlineData(null, "30d")]
    [InlineData("quarter", "quarter")]
    public async Task GetComplianceReport_ShouldDefaultPeriodTo30d(string? period, string expectedPeriod)
    {
        _mockAuditService
            .Setup(s => s.GetComplianceReportAsync(expectedPeriod))
            .ReturnsAsync(new ComplianceReport { Period = expectedPeriod, TotalEvents = 9, UniqueUsers = 3 });

        var url = period is null
            ? "/api/v1/audit/reports/compliance"
            : $"/api/v1/audit/reports/compliance?period={period}";
        var response = await _client.GetAsync(url);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var report = await response.Content.ReadFromJsonAsync<ComplianceReport>();
        Assert.Equal(expectedPeriod, report!.Period);
        Assert.Equal(3, report.UniqueUsers);
    }

    [Theory]
    [InlineData(null, "json")]
    [InlineData("csv", "csv")]
    [InlineData("CSV", "CSV")]
    public async Task ExportAuditLog_ShouldDefaultToJson_AndUseLast30Days(string? format, string expectedFormat)
    {
        DateTime capturedFrom = default;
        DateTime capturedTo = default;
        _mockAuditService
            .Setup(s => s.ExportAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>(), expectedFormat))
            .Callback<DateTime, DateTime, string>((f, t, _) => (capturedFrom, capturedTo) = (f, t))
            .ReturnsAsync(new ExportResult { Format = expectedFormat, EventCount = 5, DownloadUrl = "s3://bucket/key" });

        var url = format is null ? "/api/v1/audit/export" : $"/api/v1/audit/export?format={format}";
        var response = await _client.GetAsync(url);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var result = await response.Content.ReadFromJsonAsync<ExportResult>();
        Assert.Equal(expectedFormat, result!.Format);
        Assert.Equal(5, result.EventCount);
        Assert.True(capturedTo <= DateTime.UtcNow);
        Assert.True((capturedTo - capturedFrom).TotalDays is > 29.9 and < 30.1);
    }

    [Fact]
    public async Task ExportAuditLog_ShouldForwardExplicitRange()
    {
        var from = new DateTime(2026, 1, 1, 0, 0, 0, DateTimeKind.Utc);
        var to = new DateTime(2026, 1, 15, 0, 0, 0, DateTimeKind.Utc);
        _mockAuditService
            .Setup(s => s.ExportAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>(), "json"))
            .ReturnsAsync(new ExportResult { Format = "json", EventCount = 1, From = from, To = to });

        var response = await _client.GetAsync($"/api/v1/audit/export?from={from:o}&to={to:o}");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        _mockAuditService.Verify(
            s => s.ExportAsync(
                It.Is<DateTime>(d => d.ToUniversalTime() == from),
                It.Is<DateTime>(d => d.ToUniversalTime() == to),
                "json"),
            Times.Once);
    }

    [Theory]
    [InlineData("xml")]
    [InlineData("parquet")]
    public async Task ExportAuditLog_ShouldReturn400_ForUnsupportedFormat(string format)
    {
        var response = await _client.GetAsync($"/api/v1/audit/export?format={format}");

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Contains("Format must be 'csv' or 'json'.", await response.Content.ReadAsStringAsync());
        _mockAuditService.Verify(
            s => s.ExportAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>(), It.IsAny<string>()),
            Times.Never);
    }

    [Fact]
    public async Task ArchiveOldEvents_ShouldReturnArchiveResult()
    {
        _mockAuditService
            .Setup(s => s.ArchiveOldEventsAsync())
            .ReturnsAsync(new ArchiveResult { ArchivedCount = 7, S3Location = "s3://bucket/archive.json" });

        var response = await _client.PostAsync("/api/v1/audit/archive", null);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var result = await response.Content.ReadFromJsonAsync<ArchiveResult>();
        Assert.Equal(7, result!.ArchivedCount);
        Assert.Equal("s3://bucket/archive.json", result.S3Location);
    }

    [Fact]
    public async Task Health_ShouldReportHealthy_WhenDynamoDbResponds()
    {
        _mockDynamoDb
            .Setup(d => d.ListTablesAsync(It.IsAny<CancellationToken>()))
            .ReturnsAsync(new ListTablesResponse());

        var response = await _client.GetAsync("/health");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Contains("\"status\":\"healthy\"", await response.Content.ReadAsStringAsync());
    }

    [Fact]
    public async Task Health_ShouldReport503_WhenDynamoDbIsUnreachable()
    {
        _mockDynamoDb
            .Setup(d => d.ListTablesAsync(It.IsAny<CancellationToken>()))
            .ThrowsAsync(new AmazonDynamoDBException("unreachable"));

        var response = await _client.GetAsync("/health");

        Assert.Equal(HttpStatusCode.ServiceUnavailable, response.StatusCode);
        Assert.Contains("\"status\":\"unhealthy\"", await response.Content.ReadAsStringAsync());
    }

    [Fact]
    public async Task Metrics_ShouldExposePrometheusText()
    {
        var response = await _client.GetAsync("/metrics");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal("text/plain", response.Content.Headers.ContentType?.MediaType);
        Assert.Contains("# TYPE", await response.Content.ReadAsStringAsync());
    }
}
