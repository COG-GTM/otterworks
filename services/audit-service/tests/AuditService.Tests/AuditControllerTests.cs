using System.Net;
using System.Net.Http.Json;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using Microsoft.Extensions.Hosting;
using Moq;
using OtterWorks.AuditService.Models;
using OtterWorks.AuditService.Services;
using IAuditService = OtterWorks.AuditService.Services.IAuditService;

namespace AuditService.Tests;

public class AuditControllerTests : IDisposable
{
    private readonly Mock<IAuditService> _mockAuditService;
    private readonly AuditServiceTestHost _host;
    private readonly HttpClient _client;

    public AuditControllerTests()
    {
        _mockAuditService = new Mock<IAuditService>();
        _host = new AuditServiceTestHost(services =>
        {
            services.RemoveAll<IAuditService>();
            services.AddSingleton(_mockAuditService.Object);
        });
        _client = _host.CreateClient();
    }

    public void Dispose()
    {
        _client.Dispose();
        _host.Dispose();
    }

    [Fact]
    public async Task RecordEvent_WithValidRequest_ShouldReturn201WithLocation()
    {
        _mockAuditService
            .Setup(s => s.RecordEventAsync(It.IsAny<AuditEventRequest>()))
            .ReturnsAsync(new AuditEventResponse
            {
                Id = "evt-1",
                UserId = "user-1",
                Action = "create",
                ResourceType = "document",
                ResourceId = "doc-1",
            });

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
        Assert.NotNull(body);
        Assert.Equal("evt-1", body.Id);

        _mockAuditService.Verify(
            s => s.RecordEventAsync(It.Is<AuditEventRequest>(r => r.UserId == "user-1" && r.Action == "create")),
            Times.Once);
    }

    [Theory]
    [InlineData("", "create", "document", "doc-1")]
    [InlineData("   ", "create", "document", "doc-1")]
    [InlineData("user-1", "", "document", "doc-1")]
    [InlineData("user-1", "create", "", "doc-1")]
    [InlineData("user-1", "create", "document", "")]
    public async Task RecordEvent_WithMissingRequiredField_ShouldReturn400AndNotRecord(
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
        Assert.Contains("required", await response.Content.ReadAsStringAsync(), StringComparison.OrdinalIgnoreCase);

        _mockAuditService.Verify(s => s.RecordEventAsync(It.IsAny<AuditEventRequest>()), Times.Never);
    }

    [Fact]
    public async Task QueryEvents_ShouldForwardFiltersAndDefaultPaging()
    {
        _mockAuditService
            .Setup(s => s.QueryEventsAsync(
                It.IsAny<string?>(), It.IsAny<string?>(), It.IsAny<string?>(), It.IsAny<string?>(),
                It.IsAny<DateTime?>(), It.IsAny<DateTime?>(), It.IsAny<int>(), It.IsAny<int>()))
            .ReturnsAsync(new AuditEventPage { Total = 0, Page = 1, PageSize = 20 });

        var response = await _client.GetAsync(
            "/api/v1/audit/events?user_id=user-1&action=create&resource=doc-1&resource_type=document" +
            "&from=2026-01-01T00:00:00Z&to=2026-02-01T00:00:00Z");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);

        _mockAuditService.Verify(
            s => s.QueryEventsAsync(
                "user-1", "create", "document", "doc-1",
                It.Is<DateTime?>(d => d!.Value.Year == 2026 && d.Value.Month == 1),
                It.Is<DateTime?>(d => d!.Value.Month == 2),
                1, 20),
            Times.Once);
    }

    [Theory]
    [InlineData(0, 1)]
    [InlineData(50, 50)]
    [InlineData(1000, 100)]
    public async Task QueryEvents_ShouldClampPageSizeBetween1And100(int requestedSize, int expectedSize)
    {
        _mockAuditService
            .Setup(s => s.QueryEventsAsync(
                It.IsAny<string?>(), It.IsAny<string?>(), It.IsAny<string?>(), It.IsAny<string?>(),
                It.IsAny<DateTime?>(), It.IsAny<DateTime?>(), It.IsAny<int>(), It.IsAny<int>()))
            .ReturnsAsync(new AuditEventPage());

        var response = await _client.GetAsync($"/api/v1/audit/events?page=3&size={requestedSize}");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        _mockAuditService.Verify(
            s => s.QueryEventsAsync(null, null, null, null, null, null, 3, expectedSize),
            Times.Once);
    }

    [Fact]
    public async Task GetEvent_WhenEventExists_ShouldReturn200()
    {
        _mockAuditService
            .Setup(s => s.GetEventAsync("evt-1"))
            .ReturnsAsync(new AuditEventResponse { Id = "evt-1", UserId = "user-1" });

        var body = await _client.GetFromJsonAsync<AuditEventResponse>("/api/v1/audit/events/evt-1");

        Assert.NotNull(body);
        Assert.Equal("evt-1", body.Id);
        Assert.Equal("user-1", body.UserId);
    }

    [Fact]
    public async Task GetEvent_WhenEventMissing_ShouldReturn404()
    {
        _mockAuditService.Setup(s => s.GetEventAsync("nope")).ReturnsAsync((AuditEventResponse?)null);

        var response = await _client.GetAsync("/api/v1/audit/events/nope");

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
        Assert.Contains("Event not found", await response.Content.ReadAsStringAsync(), StringComparison.Ordinal);
    }

    [Theory]
    [InlineData(null, "30d")]
    [InlineData("7d", "7d")]
    public async Task GetUserActivityReport_ShouldDefaultPeriodTo30Days(string? period, string expectedPeriod)
    {
        _mockAuditService
            .Setup(s => s.GetUserActivityReportAsync("user-1", expectedPeriod))
            .ReturnsAsync(new UserActivityReport { UserId = "user-1", Period = expectedPeriod, TotalEvents = 7 });

        var url = period is null
            ? "/api/v1/audit/reports/user/user-1"
            : $"/api/v1/audit/reports/user/user-1?period={period}";
        var report = await _client.GetFromJsonAsync<UserActivityReport>(url);

        Assert.NotNull(report);
        Assert.Equal(expectedPeriod, report.Period);
        Assert.Equal(7, report.TotalEvents);
        _mockAuditService.Verify(s => s.GetUserActivityReportAsync("user-1", expectedPeriod), Times.Once);
    }

    [Fact]
    public async Task GetResourceHistory_ShouldReturnHistoryForResource()
    {
        _mockAuditService
            .Setup(s => s.GetResourceHistoryAsync("doc-1"))
            .ReturnsAsync(new ResourceHistory { ResourceId = "doc-1", TotalEvents = 2 });

        var history = await _client.GetFromJsonAsync<ResourceHistory>("/api/v1/audit/resources/doc-1/history");

        Assert.NotNull(history);
        Assert.Equal("doc-1", history.ResourceId);
        Assert.Equal(2, history.TotalEvents);
    }

    [Theory]
    [InlineData(null, "30d")]
    [InlineData("quarter", "quarter")]
    public async Task GetComplianceReport_ShouldDefaultPeriodTo30Days(string? period, string expectedPeriod)
    {
        _mockAuditService
            .Setup(s => s.GetComplianceReportAsync(expectedPeriod))
            .ReturnsAsync(new ComplianceReport { Period = expectedPeriod, TotalEvents = 3, UniqueUsers = 2 });

        var url = period is null
            ? "/api/v1/audit/reports/compliance"
            : $"/api/v1/audit/reports/compliance?period={period}";
        var report = await _client.GetFromJsonAsync<ComplianceReport>(url);

        Assert.NotNull(report);
        Assert.Equal(expectedPeriod, report.Period);
        Assert.Equal(3, report.TotalEvents);
        _mockAuditService.Verify(s => s.GetComplianceReportAsync(expectedPeriod), Times.Once);
    }

    [Fact]
    public async Task ExportAuditLog_WithExplicitRange_ShouldForwardFormatAndRange()
    {
        var from = new DateTime(2026, 1, 1, 0, 0, 0, DateTimeKind.Utc);
        var to = new DateTime(2026, 1, 31, 0, 0, 0, DateTimeKind.Utc);

        _mockAuditService
            .Setup(s => s.ExportAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>(), "csv"))
            .ReturnsAsync(new ExportResult { Format = "csv", EventCount = 12, DownloadUrl = "s3://bucket/export.csv" });

        var result = await _client.GetFromJsonAsync<ExportResult>(
            $"/api/v1/audit/export?format=csv&from={from:O}&to={to:O}");

        Assert.NotNull(result);
        Assert.Equal("csv", result.Format);
        Assert.Equal(12, result.EventCount);
        _mockAuditService.Verify(
            s => s.ExportAsync(
                It.Is<DateTime>(d => d.ToUniversalTime() == from),
                It.Is<DateTime>(d => d.ToUniversalTime() == to),
                "csv"),
            Times.Once);
    }

    [Fact]
    public async Task ExportAuditLog_WithoutParameters_ShouldDefaultToJsonAndLast30Days()
    {
        _mockAuditService
            .Setup(s => s.ExportAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>(), "json"))
            .ReturnsAsync(new ExportResult { Format = "json", EventCount = 0 });

        var response = await _client.GetAsync("/api/v1/audit/export");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        _mockAuditService.Verify(
            s => s.ExportAsync(
                It.Is<DateTime>(d => d <= DateTime.UtcNow.AddDays(-29) && d >= DateTime.UtcNow.AddDays(-31)),
                It.Is<DateTime>(d => d <= DateTime.UtcNow.AddMinutes(1)),
                "json"),
            Times.Once);
    }

    [Theory]
    [InlineData("xml")]
    [InlineData("parquet")]
    public async Task ExportAuditLog_WithUnsupportedFormat_ShouldReturn400(string format)
    {
        var response = await _client.GetAsync($"/api/v1/audit/export?format={format}");

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Contains("csv", await response.Content.ReadAsStringAsync(), StringComparison.Ordinal);
        _mockAuditService.Verify(
            s => s.ExportAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>(), It.IsAny<string>()),
            Times.Never);
    }

    [Theory]
    [InlineData("CSV")]
    [InlineData("Json")]
    public async Task ExportAuditLog_ShouldAcceptFormatCaseInsensitively(string format)
    {
        _mockAuditService
            .Setup(s => s.ExportAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>(), format))
            .ReturnsAsync(new ExportResult { Format = format });

        var response = await _client.GetAsync($"/api/v1/audit/export?format={format}");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        _mockAuditService.Verify(
            s => s.ExportAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>(), format),
            Times.Once);
    }

    [Fact]
    public async Task ArchiveOldEvents_ShouldReturnArchiveResult()
    {
        _mockAuditService
            .Setup(s => s.ArchiveOldEventsAsync())
            .ReturnsAsync(new ArchiveResult { ArchivedCount = 4, S3Location = "s3://bucket/archive.json" });

        var response = await _client.PostAsync("/api/v1/audit/archive", content: null);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var result = await response.Content.ReadFromJsonAsync<ArchiveResult>();
        Assert.NotNull(result);
        Assert.Equal(4, result.ArchivedCount);
        Assert.Equal("s3://bucket/archive.json", result.S3Location);
    }
}
