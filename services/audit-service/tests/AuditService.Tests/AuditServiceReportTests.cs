using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Moq;
using OtterWorks.AuditService.Config;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

public class AuditServiceReportTests
{
    private readonly Mock<IAuditRepository> _mockRepository = new();
    private readonly Mock<IAuditArchiver> _mockArchiver = new();
    private readonly Mock<ILogger<OtterWorks.AuditService.Services.AuditService>> _mockLogger = new();
    private readonly OtterWorks.AuditService.Services.AuditService _service;

    public AuditServiceReportTests()
    {
        _service = new OtterWorks.AuditService.Services.AuditService(
            _mockRepository.Object,
            _mockArchiver.Object,
            Options.Create(new AwsSettings { ArchiveAfterDays = 90 }),
            _mockLogger.Object);
    }

    [Fact]
    public async Task GetComplianceReportAsync_ShouldFlagUsersAboveTheSuspiciousThreshold()
    {
        var events = new List<AuditEvent>();
        events.AddRange(Enumerable.Range(0, 101).Select(i => CreateEvent("noisy-user", $"e{i}")));
        events.AddRange(Enumerable.Range(0, 9).Select(i => CreateEvent($"quiet-user-{i}", $"q{i}")));

        _mockRepository
            .Setup(r => r.GetEventsByDateRangeAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>()))
            .ReturnsAsync(events);

        var report = await _service.GetComplianceReportAsync("30d");

        Assert.Equal(110, report.TotalEvents);
        Assert.Equal(10, report.UniqueUsers);
        var suspicious = Assert.Single(report.SuspiciousActivities);
        Assert.Equal("noisy-user", suspicious.UserId);
        Assert.Equal(101, suspicious.EventCount);
        Assert.Contains("Unusually high activity", suspicious.Reason);
    }

    [Fact]
    public async Task GetComplianceReportAsync_ShouldReportNoSuspiciousActivity_WhenThereAreNoEvents()
    {
        _mockRepository
            .Setup(r => r.GetEventsByDateRangeAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>()))
            .ReturnsAsync(new List<AuditEvent>());

        var report = await _service.GetComplianceReportAsync("30d");

        Assert.Equal(0, report.TotalEvents);
        Assert.Empty(report.SuspiciousActivities);
        Assert.True(report.GeneratedAt <= DateTime.UtcNow);
    }

    [Theory]
    [InlineData("day", 1)]
    [InlineData("24h", 1)]
    [InlineData("week", 7)]
    [InlineData("7d", 7)]
    [InlineData("month", 30)]
    [InlineData("30d", 30)]
    [InlineData("quarter", 90)]
    [InlineData("90d", 90)]
    [InlineData("year", 365)]
    [InlineData("365d", 365)]
    [InlineData("YEAR", 365)]
    [InlineData("nonsense", 30)]
    public async Task GetUserActivityReportAsync_ShouldResolveThePeriodWindow(string period, int expectedDays)
    {
        var insideWindow = DateTime.UtcNow.AddDays(-expectedDays).AddHours(1);
        var outsideWindow = DateTime.UtcNow.AddDays(-expectedDays).AddHours(-1);

        _mockRepository
            .Setup(r => r.GetAllUserEventsAsync("user-1"))
            .ReturnsAsync(new List<AuditEvent>
            {
                CreateEvent("user-1", "inside", insideWindow),
                CreateEvent("user-1", "outside", outsideWindow),
            });

        var report = await _service.GetUserActivityReportAsync("user-1", period);

        Assert.Equal(period, report.Period);
        Assert.Equal(1, report.TotalEvents);
        Assert.Equal("inside", Assert.Single(report.RecentEvents).Id);
    }

    [Fact]
    public async Task GetUserActivityReportAsync_ShouldKeepOnlyTheTenMostRecentEvents()
    {
        var events = Enumerable.Range(0, 15)
            .Select(i => CreateEvent("user-1", $"e{i}", DateTime.UtcNow.AddMinutes(-i)))
            .ToList();

        _mockRepository
            .Setup(r => r.GetAllUserEventsAsync("user-1"))
            .ReturnsAsync(events);

        var report = await _service.GetUserActivityReportAsync("user-1", "30d");

        Assert.Equal(15, report.TotalEvents);
        Assert.Equal(10, report.RecentEvents.Count);
        Assert.Equal("e0", report.RecentEvents[0].Id);
        Assert.Equal(events[14].Timestamp, report.FirstActivity);
        Assert.Equal(events[0].Timestamp, report.LastActivity);
    }

    private static AuditEvent CreateEvent(string userId, string id, DateTime? timestamp = null) => new()
    {
        Id = id,
        UserId = userId,
        Action = "read",
        ResourceType = "file",
        ResourceId = "file-1",
        Timestamp = timestamp ?? DateTime.UtcNow,
    };
}
