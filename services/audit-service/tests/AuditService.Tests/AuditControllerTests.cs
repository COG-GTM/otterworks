using System.Net;
using System.Net.Http.Json;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using Microsoft.Extensions.Hosting;
using Moq;
using OtterWorks.AuditService.Models;
using OtterWorks.AuditService.Services;
using IAuditService = OtterWorks.AuditService.Services.IAuditService;

namespace AuditService.Tests;

[Collection(AuditApiCollection.Name)]
public class AuditControllerTests : IAsyncLifetime
{
    private readonly Mock<IAuditService> _mockAuditService = new();
    private readonly AuditApiFactory _factory;
    private readonly HttpClient _client;

    public AuditControllerTests()
    {
        _factory = new AuditApiFactory(_mockAuditService.Object);
        _client = _factory.CreateClient();
    }

    public Task InitializeAsync() => Task.CompletedTask;

    public async Task DisposeAsync()
    {
        _client.Dispose();
        await _factory.DisposeAsync();
    }

    [Fact]
    public async Task RecordEvent_ShouldReturn201_WhenRequestIsValid()
    {
        _mockAuditService
            .Setup(s => s.RecordEventAsync(It.IsAny<AuditEventRequest>()))
            .ReturnsAsync(new AuditEventResponse { Id = "evt-1", UserId = "user-1", Action = "create" });

        var response = await _client.PostAsJsonAsync("/api/v1/audit/events", new AuditEventRequest
        {
            UserId = "user-1",
            Action = "create",
            ResourceType = "document",
            ResourceId = "doc-1",
        });

        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
        Assert.Equal("/api/v1/audit/events/evt-1", response.Headers.Location?.ToString());

        var body = await response.Content.ReadFromJsonAsync<AuditEventResponse>();
        Assert.Equal("evt-1", body?.Id);
    }

    [Theory]
    [InlineData("", "create", "document", "doc-1")]
    [InlineData("   ", "create", "document", "doc-1")]
    [InlineData("user-1", "", "document", "doc-1")]
    [InlineData("user-1", "create", "", "doc-1")]
    [InlineData("user-1", "create", "document", "")]
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
        _mockAuditService.Verify(s => s.RecordEventAsync(It.IsAny<AuditEventRequest>()), Times.Never);
    }

    [Fact]
    public async Task QueryEvents_ShouldPassFiltersThrough()
    {
        _mockAuditService
            .Setup(s => s.QueryEventsAsync(
                It.IsAny<string?>(), It.IsAny<string?>(), It.IsAny<string?>(), It.IsAny<string?>(),
                It.IsAny<DateTime?>(), It.IsAny<DateTime?>(), It.IsAny<int>(), It.IsAny<int>()))
            .ReturnsAsync(new AuditEventPage { Total = 1, Page = 2, PageSize = 50 });

        var response = await _client.GetAsync(
            "/api/v1/audit/events?user_id=user-1&action=create&resource_type=document&resource=doc-1" +
            "&from=2026-01-01T00:00:00Z&to=2026-02-01T00:00:00Z&page=2&size=50");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var page = await response.Content.ReadFromJsonAsync<AuditEventPage>();
        Assert.Equal(1, page?.Total);

        _mockAuditService.Verify(s => s.QueryEventsAsync(
            "user-1", "create", "document", "doc-1",
            It.IsAny<DateTime?>(), It.IsAny<DateTime?>(), 2, 50), Times.Once);
    }

    [Theory]
    [InlineData(null, 1, 20)]
    [InlineData(0, 1, 1)]
    [InlineData(500, 1, 100)]
    public async Task QueryEvents_ShouldClampPageSize(int? size, int expectedPage, int expectedSize)
    {
        _mockAuditService
            .Setup(s => s.QueryEventsAsync(
                It.IsAny<string?>(), It.IsAny<string?>(), It.IsAny<string?>(), It.IsAny<string?>(),
                It.IsAny<DateTime?>(), It.IsAny<DateTime?>(), It.IsAny<int>(), It.IsAny<int>()))
            .ReturnsAsync(new AuditEventPage());

        var query = size is null ? string.Empty : $"?size={size}";
        var response = await _client.GetAsync($"/api/v1/audit/events{query}");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        _mockAuditService.Verify(s => s.QueryEventsAsync(
            null, null, null, null, null, null, expectedPage, expectedSize), Times.Once);
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
        Assert.Equal("evt-1", body?.Id);
    }

    [Fact]
    public async Task GetEvent_ShouldReturn404_WhenEventIsMissing()
    {
        _mockAuditService
            .Setup(s => s.GetEventAsync("missing"))
            .ReturnsAsync((AuditEventResponse?)null);

        var response = await _client.GetAsync("/api/v1/audit/events/missing");

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }

    [Theory]
    [InlineData("?period=7d", "7d")]
    [InlineData("", "30d")]
    public async Task GetUserActivityReport_ShouldDefaultPeriod(string query, string expectedPeriod)
    {
        _mockAuditService
            .Setup(s => s.GetUserActivityReportAsync("user-1", expectedPeriod))
            .ReturnsAsync(new UserActivityReport { UserId = "user-1", Period = expectedPeriod });

        var response = await _client.GetAsync($"/api/v1/audit/reports/user/user-1{query}");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var report = await response.Content.ReadFromJsonAsync<UserActivityReport>();
        Assert.Equal(expectedPeriod, report?.Period);
    }

    [Fact]
    public async Task GetResourceHistory_ShouldReturnHistory()
    {
        _mockAuditService
            .Setup(s => s.GetResourceHistoryAsync("doc-1"))
            .ReturnsAsync(new ResourceHistory { ResourceId = "doc-1", TotalEvents = 3 });

        var response = await _client.GetAsync("/api/v1/audit/resources/doc-1/history");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var history = await response.Content.ReadFromJsonAsync<ResourceHistory>();
        Assert.Equal(3, history?.TotalEvents);
    }

    [Theory]
    [InlineData("?period=90d", "90d")]
    [InlineData("", "30d")]
    public async Task GetComplianceReport_ShouldDefaultPeriod(string query, string expectedPeriod)
    {
        _mockAuditService
            .Setup(s => s.GetComplianceReportAsync(expectedPeriod))
            .ReturnsAsync(new ComplianceReport { Period = expectedPeriod, TotalEvents = 7 });

        var response = await _client.GetAsync($"/api/v1/audit/reports/compliance{query}");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var report = await response.Content.ReadFromJsonAsync<ComplianceReport>();
        Assert.Equal(7, report?.TotalEvents);
    }

    [Theory]
    [InlineData("?format=csv", "csv")]
    [InlineData("?format=JSON", "JSON")]
    [InlineData("", "json")]
    public async Task ExportAuditLog_ShouldAcceptSupportedFormats(string query, string expectedFormat)
    {
        _mockAuditService
            .Setup(s => s.ExportAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>(), expectedFormat))
            .ReturnsAsync(new ExportResult { Format = expectedFormat, EventCount = 2 });

        var response = await _client.GetAsync($"/api/v1/audit/export{query}");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var result = await response.Content.ReadFromJsonAsync<ExportResult>();
        Assert.Equal(2, result?.EventCount);
    }

    [Fact]
    public async Task ExportAuditLog_ShouldPassExplicitDateRange()
    {
        var from = new DateTime(2026, 1, 1, 0, 0, 0, DateTimeKind.Utc);
        var to = new DateTime(2026, 2, 1, 0, 0, 0, DateTimeKind.Utc);

        _mockAuditService
            .Setup(s => s.ExportAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>(), "json"))
            .ReturnsAsync(new ExportResult { From = from, To = to });

        var response = await _client.GetAsync(
            "/api/v1/audit/export?from=2026-01-01T00:00:00Z&to=2026-02-01T00:00:00Z");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        _mockAuditService.Verify(s => s.ExportAsync(
            It.Is<DateTime>(d => d.ToUniversalTime() == from),
            It.Is<DateTime>(d => d.ToUniversalTime() == to),
            "json"), Times.Once);
    }

    [Fact]
    public async Task ExportAuditLog_ShouldReturn400_WhenFormatIsUnsupported()
    {
        var response = await _client.GetAsync("/api/v1/audit/export?format=xml");

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        _mockAuditService.Verify(
            s => s.ExportAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>(), It.IsAny<string>()),
            Times.Never);
    }

    [Fact]
    public async Task ArchiveOldEvents_ShouldReturnArchiveResult()
    {
        _mockAuditService
            .Setup(s => s.ArchiveOldEventsAsync())
            .ReturnsAsync(new ArchiveResult { ArchivedCount = 12, S3Location = "s3://bucket/key" });

        var response = await _client.PostAsync("/api/v1/audit/archive", null);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var result = await response.Content.ReadFromJsonAsync<ArchiveResult>();
        Assert.Equal(12, result?.ArchivedCount);
        Assert.Equal("s3://bucket/key", result?.S3Location);
    }

    private sealed class AuditApiFactory : WebApplicationFactory<Program>
    {
        private readonly IAuditService _auditService;

        public AuditApiFactory(IAuditService auditService)
        {
            _auditService = auditService;
        }

        protected override void ConfigureWebHost(IWebHostBuilder builder)
        {
            builder.ConfigureServices(services =>
            {
                // Drops the SnsConsumer background loop so nothing talks to SQS.
                services.RemoveAll<IHostedService>();
                services.RemoveAll<IAuditService>();
                services.AddSingleton(_auditService);
            });
        }
    }
}
