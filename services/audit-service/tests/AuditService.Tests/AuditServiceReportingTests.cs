using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Moq;
using OtterWorks.AuditService.Config;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

public class AuditServiceReportingTests
{
    private readonly Mock<IAuditRepository> _mockRepository = new();
    private readonly Mock<IAuditArchiver> _mockArchiver = new();
    private readonly Mock<ILogger<OtterWorks.AuditService.Services.AuditService>> _mockLogger = new();
    private readonly OtterWorks.AuditService.Services.AuditService _service;

    public AuditServiceReportingTests()
    {
        _service = new OtterWorks.AuditService.Services.AuditService(
            _mockRepository.Object,
            _mockArchiver.Object,
            Options.Create(new AwsSettings { ArchiveAfterDays = 90 }),
            _mockLogger.Object);
    }

    [Fact]
    public async Task GetComplianceReportAsync_ShouldFlagUsersAboveThreshold()
    {
        var events = new List<AuditEvent>();
        for (var i = 0; i < 200; i++)
            events.Add(NewEvent("noisy-user", "read", "file", DateTime.UtcNow.AddMinutes(-i)));
        for (var u = 0; u < 9; u++)
            events.Add(NewEvent($"quiet-user-{u}", "update", "document", DateTime.UtcNow.AddMinutes(-u)));

        _mockRepository
            .Setup(r => r.GetEventsByDateRangeAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>()))
            .ReturnsAsync(events);

        var report = await _service.GetComplianceReportAsync("30d");

        Assert.Equal(209, report.TotalEvents);
        Assert.Equal(10, report.UniqueUsers);
        Assert.Equal(200, report.ActionBreakdown["read"]);
        Assert.Equal(9, report.ResourceTypeBreakdown["document"]);
        var suspicious = Assert.Single(report.SuspiciousActivities);
        Assert.Equal("noisy-user", suspicious.UserId);
        Assert.Equal(200, suspicious.EventCount);
        Assert.Contains("Unusually high activity", suspicious.Reason);
        Assert.True(report.GeneratedAt <= DateTime.UtcNow);
    }

    [Fact]
    public async Task GetComplianceReportAsync_ShouldReportNoSuspiciousActivity_WhenThereAreNoEvents()
    {
        _mockRepository
            .Setup(r => r.GetEventsByDateRangeAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>()))
            .ReturnsAsync(new List<AuditEvent>());

        var report = await _service.GetComplianceReportAsync("unknown-period");

        Assert.Equal(0, report.TotalEvents);
        Assert.Equal(0, report.UniqueUsers);
        Assert.Empty(report.SuspiciousActivities);
        Assert.Empty(report.ActionBreakdown);
    }

    [Theory]
    [InlineData("day", 1)]
    [InlineData("24h", 1)]
    [InlineData("week", 7)]
    [InlineData("7d", 7)]
    [InlineData("Month", 30)]
    [InlineData("30d", 30)]
    [InlineData("quarter", 90)]
    [InlineData("90d", 90)]
    [InlineData("year", 365)]
    [InlineData("365d", 365)]
    [InlineData("nonsense", 30)]
    public async Task GetUserActivityReportAsync_ShouldFilterEventsToThePeriodWindow(string period, int expectedDays)
    {
        var insideWindow = NewEvent("user-1", "read", "file", DateTime.UtcNow.AddDays(-expectedDays).AddHours(1));
        var outsideWindow = NewEvent("user-1", "delete", "file", DateTime.UtcNow.AddDays(-expectedDays).AddHours(-1));
        var future = NewEvent("user-1", "share", "file", DateTime.UtcNow.AddDays(1));

        _mockRepository
            .Setup(r => r.GetAllUserEventsAsync("user-1"))
            .ReturnsAsync(new List<AuditEvent> { insideWindow, outsideWindow, future });

        var report = await _service.GetUserActivityReportAsync("user-1", period);

        Assert.Equal(period, report.Period);
        Assert.Equal(1, report.TotalEvents);
        Assert.Equal(1, report.ActionCounts["read"]);
        Assert.False(report.ActionCounts.ContainsKey("delete"));
        Assert.Equal(insideWindow.Timestamp, report.FirstActivity);
        Assert.Equal(insideWindow.Timestamp, report.LastActivity);
        Assert.Equal("read", Assert.Single(report.RecentEvents).Action);
    }

    [Fact]
    public async Task GetUserActivityReportAsync_ShouldReturnAtMostTenMostRecentEvents()
    {
        var events = Enumerable.Range(0, 15)
            .Select(i => NewEvent("user-1", $"action-{i}", "file", DateTime.UtcNow.AddMinutes(-i)))
            .ToList();
        _mockRepository.Setup(r => r.GetAllUserEventsAsync("user-1")).ReturnsAsync(events);

        var report = await _service.GetUserActivityReportAsync("user-1", "7d");

        Assert.Equal(15, report.TotalEvents);
        Assert.Equal(10, report.RecentEvents.Count);
        Assert.Equal("action-0", report.RecentEvents[0].Action);
        Assert.Equal("action-9", report.RecentEvents[9].Action);
    }

    private static AuditEvent NewEvent(string userId, string action, string resourceType, DateTime timestamp) => new()
    {
        Id = Guid.NewGuid().ToString(),
        UserId = userId,
        Action = action,
        ResourceType = resourceType,
        ResourceId = "resource-1",
        Timestamp = timestamp,
    };
}
