using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Moq;
using OtterWorks.AuditService.Config;
using OtterWorks.AuditService.Models;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

public class AuditServiceTests
{
    private readonly Mock<IAuditRepository> _mockRepository;
    private readonly Mock<IAuditArchiver> _mockArchiver;
    private readonly Mock<ILogger<OtterWorks.AuditService.Services.AuditService>> _mockLogger;
    private readonly IOptions<AwsSettings> _options;
    private readonly OtterWorks.AuditService.Services.AuditService _service;

    public AuditServiceTests()
    {
        _mockRepository = new Mock<IAuditRepository>();
        _mockArchiver = new Mock<IAuditArchiver>();
        _mockLogger = new Mock<ILogger<OtterWorks.AuditService.Services.AuditService>>();
        _options = Options.Create(new AwsSettings
        {
            Region = "us-east-1",
            DynamoDbTable = "test-table",
            S3ArchiveBucket = "test-bucket",
            ArchiveAfterDays = 90,
        });

        _service = new OtterWorks.AuditService.Services.AuditService(
            _mockRepository.Object,
            _mockArchiver.Object,
            _options,
            Options.Create(new AuditLimits { MaxReportEvents = 100, MaxResourceHistoryEvents = 50 }),
            _mockLogger.Object);
    }

    [Fact]
    public async Task RecordEventAsync_ShouldSaveAndReturnEvent()
    {
        var request = new AuditEventRequest
        {
            UserId = "user-123",
            Action = "create",
            ResourceType = "document",
            ResourceId = "doc-456",
            IpAddress = "192.168.1.1",
            UserAgent = "TestAgent/1.0",
        };

        _mockRepository
            .Setup(r => r.SaveEventAsync(It.IsAny<AuditEvent>()))
            .Returns(Task.CompletedTask);

        var result = await _service.RecordEventAsync(request);

        Assert.NotNull(result);
        Assert.Equal("user-123", result.UserId);
        Assert.Equal("create", result.Action);
        Assert.Equal("document", result.ResourceType);
        Assert.Equal("doc-456", result.ResourceId);
        Assert.Equal("192.168.1.1", result.IpAddress);
        Assert.Equal("TestAgent/1.0", result.UserAgent);
        Assert.NotEmpty(result.Id);

        _mockRepository.Verify(r => r.SaveEventAsync(It.Is<AuditEvent>(
            e => e.UserId == "user-123" && e.Action == "create")), Times.Once);
    }

    [Fact]
    public async Task RecordEventAsync_ShouldAssignTimestamp()
    {
        var request = new AuditEventRequest
        {
            UserId = "user-1",
            Action = "login",
            ResourceType = "user",
            ResourceId = "user-1",
        };

        _mockRepository.Setup(r => r.SaveEventAsync(It.IsAny<AuditEvent>())).Returns(Task.CompletedTask);

        var before = DateTime.UtcNow;
        var result = await _service.RecordEventAsync(request);
        var after = DateTime.UtcNow;

        Assert.InRange(result.Timestamp, before, after);
    }

    [Fact]
    public async Task GetEventAsync_WhenEventExists_ShouldReturnEvent()
    {
        var auditEvent = CreateSampleEvent("evt-1");
        _mockRepository.Setup(r => r.GetEventAsync("evt-1")).ReturnsAsync(auditEvent);

        var result = await _service.GetEventAsync("evt-1");

        Assert.NotNull(result);
        Assert.Equal("evt-1", result.Id);
        Assert.Equal("user-1", result.UserId);
    }

    [Fact]
    public async Task GetEventAsync_WhenEventNotFound_ShouldReturnNull()
    {
        _mockRepository.Setup(r => r.GetEventAsync("nonexistent")).ReturnsAsync((AuditEvent?)null);

        var result = await _service.GetEventAsync("nonexistent");

        Assert.Null(result);
    }

    [Fact]
    public async Task QueryEventsAsync_ShouldDelegateToRepository()
    {
        var page = new AuditEventPage
        {
            Events = new List<AuditEvent> { CreateSampleEvent("evt-1") },
            Total = 1,
            Page = 1,
            PageSize = 20,
        };

        _mockRepository
            .Setup(r => r.QueryEventsAsync("user-1", "create", null, null, null, null, 1, 20))
            .ReturnsAsync(page);

        var result = await _service.QueryEventsAsync("user-1", "create", null, null, null, null, 1, 20);

        Assert.Equal(1, result.Total);
        Assert.Single(result.Events);
        Assert.Equal(1, result.Page);
    }

    [Fact]
    public async Task GetUserActivityReportAsync_ShouldBuildCorrectReport()
    {
        var events = new List<AuditEvent>
        {
            CreateSampleEvent("e1", action: "create", resourceType: "document"),
            CreateSampleEvent("e2", action: "create", resourceType: "file"),
            CreateSampleEvent("e3", action: "delete", resourceType: "document"),
        };

        _mockRepository
            .Setup(r => r.StreamUserEventsAsync("user-1", It.IsAny<DateTime>(), It.IsAny<DateTime>(), It.IsAny<CancellationToken>()))
            .Returns(events.ToAsyncEnumerable());

        var report = await _service.GetUserActivityReportAsync("user-1", "30d");

        Assert.Equal("user-1", report.UserId);
        Assert.Equal("30d", report.Period);
        Assert.Equal(3, report.TotalEvents);
        Assert.Equal(2, report.ActionCounts["create"]);
        Assert.Equal(1, report.ActionCounts["delete"]);
        Assert.Equal(2, report.ResourceTypeCounts["document"]);
        Assert.Equal(1, report.ResourceTypeCounts["file"]);
        Assert.False(report.Truncated);
    }

    [Fact]
    public async Task GetUserActivityReportAsync_ShouldCapEventsAndKeepNewestRecent()
    {
        var now = DateTime.UtcNow;
        var events = Enumerable.Range(1, 150)
            .Select(i =>
            {
                var e = CreateSampleEvent($"e{i}");
                e.Timestamp = now.AddMinutes(-i);
                return e;
            })
            .ToList();

        _mockRepository
            .Setup(r => r.StreamUserEventsAsync("user-1", It.IsAny<DateTime>(), It.IsAny<DateTime>(), It.IsAny<CancellationToken>()))
            .Returns(events.ToAsyncEnumerable());

        var report = await _service.GetUserActivityReportAsync("user-1", "30d");

        Assert.Equal(100, report.TotalEvents);
        Assert.True(report.Truncated);
        Assert.Equal(Enumerable.Range(1, 10).Select(i => $"e{i}"), report.RecentEvents.Select(e => e.Id));
        Assert.Equal(now.AddMinutes(-1), report.LastActivity);
        Assert.Equal(now.AddMinutes(-100), report.FirstActivity);
    }

    [Fact]
    public async Task GetResourceHistoryAsync_ShouldReturnHistory()
    {
        var events = new List<AuditEvent>
        {
            CreateSampleEvent("e1", resourceId: "doc-1"),
            CreateSampleEvent("e2", resourceId: "doc-1"),
        };

        _mockRepository
            .Setup(r => r.GetResourceHistoryAsync("doc-1", 50))
            .ReturnsAsync(new AuditEventPage { Events = events, Total = 7, Page = 1, PageSize = 50 });

        var history = await _service.GetResourceHistoryAsync("doc-1");

        Assert.Equal("doc-1", history.ResourceId);
        Assert.Equal(7, history.TotalEvents);
        Assert.Equal(2, history.Events.Count);
    }

    [Fact]
    public async Task GetComplianceReportAsync_ShouldBuildCorrectReport()
    {
        var events = new List<AuditEvent>
        {
            CreateSampleEvent("e1", userId: "user-1", action: "create"),
            CreateSampleEvent("e2", userId: "user-2", action: "read"),
            CreateSampleEvent("e3", userId: "user-1", action: "update"),
        };

        _mockRepository
            .Setup(r => r.StreamEventsByDateRangeAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>(), It.IsAny<CancellationToken>()))
            .Returns(events.ToAsyncEnumerable());

        var report = await _service.GetComplianceReportAsync("30d");

        Assert.Equal("30d", report.Period);
        Assert.Equal(3, report.TotalEvents);
        Assert.Equal(2, report.UniqueUsers);
        Assert.Equal(1, report.ActionBreakdown["create"]);
        Assert.Equal(1, report.ActionBreakdown["read"]);
        Assert.Equal(1, report.ActionBreakdown["update"]);
        Assert.False(report.Truncated);
    }

    [Fact]
    public async Task GetComplianceReportAsync_ShouldCapEventsAndMarkTruncated()
    {
        var events = Enumerable.Range(1, 150).Select(i => CreateSampleEvent($"e{i}")).ToList();

        _mockRepository
            .Setup(r => r.StreamEventsByDateRangeAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>(), It.IsAny<CancellationToken>()))
            .Returns(events.ToAsyncEnumerable());

        var report = await _service.GetComplianceReportAsync("30d");

        Assert.Equal(100, report.TotalEvents);
        Assert.True(report.Truncated);
    }

    [Fact]
    public async Task ExportAsync_ShouldDelegateToArchiver()
    {
        var from = DateTime.UtcNow.AddDays(-7);
        var to = DateTime.UtcNow;
        var expected = new ExportResult
        {
            Format = "json",
            EventCount = 10,
            DownloadUrl = "s3://bucket/key.json",
            From = from,
            To = to,
        };

        _mockArchiver.Setup(a => a.ExportAsync(from, to, "json")).ReturnsAsync(expected);

        var result = await _service.ExportAsync(from, to, "json");

        Assert.Equal("json", result.Format);
        Assert.Equal(10, result.EventCount);
        Assert.Equal("s3://bucket/key.json", result.DownloadUrl);
    }

    [Fact]
    public async Task ArchiveOldEventsAsync_ShouldUseCutoffBasedOnSettings()
    {
        var expected = new ArchiveResult
        {
            ArchivedCount = 5,
            S3Location = "s3://bucket/archive.json",
            ArchivedBefore = DateTime.UtcNow.AddDays(-90),
        };

        _mockArchiver
            .Setup(a => a.ArchiveOldEventsAsync(It.IsAny<DateTime>()))
            .ReturnsAsync(expected);

        var result = await _service.ArchiveOldEventsAsync();

        Assert.Equal(5, result.ArchivedCount);
        _mockArchiver.Verify(a => a.ArchiveOldEventsAsync(
            It.Is<DateTime>(d => d < DateTime.UtcNow.AddDays(-89))), Times.Once);
    }

    private static AuditEvent CreateSampleEvent(
        string id = "test-id",
        string userId = "user-1",
        string action = "create",
        string resourceType = "document",
        string resourceId = "doc-1")
    {
        return new AuditEvent
        {
            Id = id,
            UserId = userId,
            Action = action,
            ResourceType = resourceType,
            ResourceId = resourceId,
            Timestamp = DateTime.UtcNow,
            IpAddress = "10.0.0.1",
            UserAgent = "TestAgent",
        };
    }
}
