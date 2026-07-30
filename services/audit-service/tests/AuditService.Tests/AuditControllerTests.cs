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
    private readonly Mock<IAuditService> _auditService = new();
    private readonly WebApplicationFactory<Program> _factory;

    public AuditControllerTests()
    {
        _factory = new WebApplicationFactory<Program>()
            .WithWebHostBuilder(builder => builder.ConfigureServices(services =>
            {
                services.RemoveAll<IHostedService>();
                services.RemoveAll<IAuditService>();
                services.AddSingleton(_auditService.Object);
            }));
    }

    public void Dispose() => _factory.Dispose();

    [Fact]
    public async Task RecordEvent_Returns201WithLocation_WhenRequestIsValid()
    {
        var request = new AuditEventRequest
        {
            UserId = "user-1",
            Action = "read",
            ResourceType = "file",
            ResourceId = "file-1",
            IpAddress = "10.0.0.1",
        };
        _auditService
            .Setup(s => s.RecordEventAsync(It.Is<AuditEventRequest>(r => r.UserId == "user-1")))
            .ReturnsAsync(new AuditEventResponse
            {
                Id = "evt-1",
                UserId = "user-1",
                Action = "read",
                ResourceType = "file",
                ResourceId = "file-1",
            });

        using var client = CreateClient();
        var response = await client.PostAsJsonAsync("/api/v1/audit/events", request);

        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
        Assert.Equal("/api/v1/audit/events/evt-1", response.Headers.Location?.ToString());
        var body = await response.Content.ReadFromJsonAsync<AuditEventResponse>();
        Assert.Equal("evt-1", body!.Id);
        _auditService.Verify(s => s.RecordEventAsync(It.IsAny<AuditEventRequest>()), Times.Once);
    }

    [Theory]
    [InlineData("", "read", "file", "file-1")]
    [InlineData("   ", "read", "file", "file-1")]
    [InlineData("user-1", "", "file", "file-1")]
    [InlineData("user-1", "read", "", "file-1")]
    [InlineData("user-1", "read", "file", "")]
    public async Task RecordEvent_Returns400_WhenRequiredFieldIsMissing(
        string userId, string action, string resourceType, string resourceId)
    {
        using var client = CreateClient();

        var response = await client.PostAsJsonAsync("/api/v1/audit/events", new AuditEventRequest
        {
            UserId = userId,
            Action = action,
            ResourceType = resourceType,
            ResourceId = resourceId,
        });

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        var body = await response.Content.ReadFromJsonAsync<ErrorBody>();
        Assert.Equal("UserId, Action, ResourceType, and ResourceId are required.", body!.Error);
        _auditService.Verify(s => s.RecordEventAsync(It.IsAny<AuditEventRequest>()), Times.Never);
    }

    [Fact]
    public async Task QueryEvents_PassesEveryFilterThrough()
    {
        var from = new DateTime(2026, 1, 1, 0, 0, 0, DateTimeKind.Utc);
        var to = new DateTime(2026, 2, 1, 0, 0, 0, DateTimeKind.Utc);
        _auditService
            .Setup(s => s.QueryEventsAsync("user-1", "read", "file", "file-1", from, to, 3, 50))
            .ReturnsAsync(new AuditEventPage { Total = 1, Page = 3, PageSize = 50 });

        using var client = CreateClient();
        var response = await client.GetAsync(
            "/api/v1/audit/events?user_id=user-1&action=read&resource_type=file&resource=file-1" +
            "&from=2026-01-01T00:00:00Z&to=2026-02-01T00:00:00Z&page=3&size=50");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var page = await response.Content.ReadFromJsonAsync<AuditEventPage>();
        Assert.Equal(3, page!.Page);
        Assert.Equal(50, page.PageSize);
        _auditService.VerifyAll();
    }

    [Theory]
    [InlineData(null, 20)]
    [InlineData(0, 1)]
    [InlineData(1, 1)]
    [InlineData(100, 100)]
    [InlineData(500, 100)]
    public async Task QueryEvents_ClampsPageSizeAndDefaultsToPageOne(int? size, int expectedPageSize)
    {
        _auditService
            .Setup(s => s.QueryEventsAsync(null, null, null, null, null, null, 1, expectedPageSize))
            .ReturnsAsync(new AuditEventPage { Page = 1, PageSize = expectedPageSize });

        using var client = CreateClient();
        var query = size is null ? string.Empty : $"?size={size}";
        var response = await client.GetAsync("/api/v1/audit/events" + query);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        _auditService.VerifyAll();
    }

    [Fact]
    public async Task GetEvent_Returns200_WhenEventExists()
    {
        _auditService
            .Setup(s => s.GetEventAsync("evt-1"))
            .ReturnsAsync(new AuditEventResponse { Id = "evt-1", UserId = "user-1" });

        using var client = CreateClient();
        var response = await client.GetAsync("/api/v1/audit/events/evt-1");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var body = await response.Content.ReadFromJsonAsync<AuditEventResponse>();
        Assert.Equal("evt-1", body!.Id);
    }

    [Fact]
    public async Task GetEvent_Returns404_WhenEventIsMissing()
    {
        _auditService.Setup(s => s.GetEventAsync("nope")).ReturnsAsync((AuditEventResponse?)null);

        using var client = CreateClient();
        var response = await client.GetAsync("/api/v1/audit/events/nope");

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
        var body = await response.Content.ReadFromJsonAsync<ErrorBody>();
        Assert.Equal("Event not found.", body!.Error);
    }

    [Theory]
    [InlineData(null, "30d")]
    [InlineData("7d", "7d")]
    public async Task GetUserActivityReport_DefaultsPeriodTo30Days(string? period, string expectedPeriod)
    {
        _auditService
            .Setup(s => s.GetUserActivityReportAsync("user-1", expectedPeriod))
            .ReturnsAsync(new UserActivityReport { UserId = "user-1", Period = expectedPeriod, TotalEvents = 2 });

        using var client = CreateClient();
        var query = period is null ? string.Empty : $"?period={period}";
        var response = await client.GetAsync("/api/v1/audit/reports/user/user-1" + query);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var report = await response.Content.ReadFromJsonAsync<UserActivityReport>();
        Assert.Equal(expectedPeriod, report!.Period);
        Assert.Equal(2, report.TotalEvents);
    }

    [Fact]
    public async Task GetResourceHistory_ReturnsHistoryForResource()
    {
        _auditService
            .Setup(s => s.GetResourceHistoryAsync("file-1"))
            .ReturnsAsync(new ResourceHistory { ResourceId = "file-1", TotalEvents = 3 });

        using var client = CreateClient();
        var response = await client.GetAsync("/api/v1/audit/resources/file-1/history");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var history = await response.Content.ReadFromJsonAsync<ResourceHistory>();
        Assert.Equal("file-1", history!.ResourceId);
        Assert.Equal(3, history.TotalEvents);
    }

    [Theory]
    [InlineData(null, "30d")]
    [InlineData("quarter", "quarter")]
    public async Task GetComplianceReport_DefaultsPeriodTo30Days(string? period, string expectedPeriod)
    {
        _auditService
            .Setup(s => s.GetComplianceReportAsync(expectedPeriod))
            .ReturnsAsync(new ComplianceReport { Period = expectedPeriod, TotalEvents = 7, UniqueUsers = 2 });

        using var client = CreateClient();
        var query = period is null ? string.Empty : $"?period={period}";
        var response = await client.GetAsync("/api/v1/audit/reports/compliance" + query);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var report = await response.Content.ReadFromJsonAsync<ComplianceReport>();
        Assert.Equal(expectedPeriod, report!.Period);
        Assert.Equal(2, report.UniqueUsers);
    }

    [Fact]
    public async Task ExportAuditLog_DefaultsToJsonOverTheLastThirtyDays()
    {
        DateTime capturedFrom = default;
        DateTime capturedTo = default;
        _auditService
            .Setup(s => s.ExportAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>(), "json"))
            .Callback<DateTime, DateTime, string>((f, t, _) => (capturedFrom, capturedTo) = (f, t))
            .ReturnsAsync(new ExportResult { Format = "json", EventCount = 5, DownloadUrl = "s3://bucket/key" });

        using var client = CreateClient();
        var before = DateTime.UtcNow;
        var response = await client.GetAsync("/api/v1/audit/export");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var result = await response.Content.ReadFromJsonAsync<ExportResult>();
        Assert.Equal("json", result!.Format);
        Assert.Equal(5, result.EventCount);
        Assert.True(capturedTo >= before);
        Assert.Equal(-30, Math.Round((capturedFrom - capturedTo).TotalDays));
    }

    [Fact]
    public async Task ExportAuditLog_UsesExplicitCsvRange()
    {
        var from = new DateTime(2026, 3, 1, 0, 0, 0, DateTimeKind.Utc);
        var to = new DateTime(2026, 3, 8, 0, 0, 0, DateTimeKind.Utc);
        _auditService
            .Setup(s => s.ExportAsync(from, to, "CSV"))
            .ReturnsAsync(new ExportResult { Format = "CSV", EventCount = 1, From = from, To = to });

        using var client = CreateClient();
        var response = await client.GetAsync(
            "/api/v1/audit/export?format=CSV&from=2026-03-01T00:00:00Z&to=2026-03-08T00:00:00Z");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        _auditService.VerifyAll();
    }

    [Fact]
    public async Task ExportAuditLog_Returns400_WhenFormatIsUnsupported()
    {
        using var client = CreateClient();

        var response = await client.GetAsync("/api/v1/audit/export?format=xml");

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        var body = await response.Content.ReadFromJsonAsync<ErrorBody>();
        Assert.Equal("Format must be 'csv' or 'json'.", body!.Error);
        _auditService.Verify(
            s => s.ExportAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>(), It.IsAny<string>()),
            Times.Never);
    }

    [Fact]
    public async Task ArchiveOldEvents_ReturnsArchiveResult()
    {
        _auditService
            .Setup(s => s.ArchiveOldEventsAsync())
            .ReturnsAsync(new ArchiveResult { ArchivedCount = 12, S3Location = "s3://bucket/archive" });

        using var client = CreateClient();
        var response = await client.PostAsync("/api/v1/audit/archive", content: null);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var result = await response.Content.ReadFromJsonAsync<ArchiveResult>();
        Assert.Equal(12, result!.ArchivedCount);
        Assert.Equal("s3://bucket/archive", result.S3Location);
    }

    private HttpClient CreateClient() => _factory.CreateClient();

    private sealed record ErrorBody(string Error);
}
