using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Moq;
using OtterWorks.AuditService.Config;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

/// <summary>
/// Covers the reporting paths of <see cref="OtterWorks.AuditService.Services.AuditService"/>:
/// period parsing, activity windowing and suspicious-activity detection.
/// </summary>
public class AuditServiceReportTests
{
    private readonly Mock<IAuditRepository> _mockRepository;
    private readonly Mock<IAuditArchiver> _mockArchiver;
    private readonly OtterWorks.AuditService.Services.AuditService _service;

    public AuditServiceReportTests()
    {
        _mockRepository = new Mock<IAuditRepository>();
        _mockArchiver = new Mock<IAuditArchiver>();
        _service = new OtterWorks.AuditService.Services.AuditService(
            _mockRepository.Object,
            _mockArchiver.Object,
            Options.Create(new AwsSettings { ArchiveAfterDays = 90 }),
            new Mock<ILogger<OtterWorks.AuditService.Services.AuditService>>().Object);
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
    [InlineData("WEEK", 7)]
    [InlineData("nonsense", 30)]
    public async Task GetComplianceReportAsync_ShouldTranslatePeriodIntoDateRange(string period, int expectedDays)
    {
        DateTime capturedFrom = default;
        DateTime capturedTo = default;

        _mockRepository
            .Setup(r => r.GetEventsByDateRangeAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>()))
            .Callback<DateTime, DateTime>((from, to) => (capturedFrom, capturedTo) = (from, to))
            .ReturnsAsync(new List<AuditEvent>());

        var report = await _service.GetComplianceReportAsync(period);

        Assert.Equal(period, report.Period);
        Assert.Equal(0, report.TotalEvents);
        Assert.Empty(report.SuspiciousActivities);
        Assert.Equal(expectedDays, Math.Round((capturedTo - capturedFrom).TotalDays));
        Assert.True(report.GeneratedAt <= DateTime.UtcNow);
    }

    [Fact]
    public async Task GetComplianceReportAsync_ShouldFlagUsersAboveTheActivityThreshold()
    {
        var events = new List<AuditEvent>();
        for (var i = 0; i < 101; i++)
        {
            events.Add(CreateEvent("noisy-user", "read"));
        }

        for (var i = 0; i < 5; i++)
        {
            events.Add(CreateEvent($"quiet-user-{i}", "read"));
        }

        _mockRepository
            .Setup(r => r.GetEventsByDateRangeAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>()))
            .ReturnsAsync(events);

        var report = await _service.GetComplianceReportAsync("30d");

        var suspicious = Assert.Single(report.SuspiciousActivities);
        Assert.Equal("noisy-user", suspicious.UserId);
        Assert.Equal(101, suspicious.EventCount);
        Assert.Contains("Unusually high activity", suspicious.Reason, StringComparison.Ordinal);
        Assert.Equal(6, report.UniqueUsers);
        Assert.Equal(106, report.TotalEvents);
    }

    [Fact]
    public async Task GetComplianceReportAsync_WithBalancedActivity_ShouldFlagNobody()
    {
        var events = Enumerable.Range(0, 6)
            .SelectMany(i => Enumerable.Repeat(CreateEvent($"user-{i}", "read"), 50))
            .ToList();

        _mockRepository
            .Setup(r => r.GetEventsByDateRangeAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>()))
            .ReturnsAsync(events);

        var report = await _service.GetComplianceReportAsync("30d");

        Assert.Empty(report.SuspiciousActivities);
        Assert.Equal(300, report.TotalEvents);
    }

    [Fact]
    public async Task GetUserActivityReportAsync_ShouldExcludeEventsOutsideThePeriod()
    {
        var events = new List<AuditEvent>
        {
            CreateEvent("user-1", "create", DateTime.UtcNow.AddHours(-1)),
            CreateEvent("user-1", "delete", DateTime.UtcNow.AddDays(-3)),
            CreateEvent("user-1", "read", DateTime.UtcNow.AddDays(-40)),
        };

        _mockRepository.Setup(r => r.GetAllUserEventsAsync("user-1")).ReturnsAsync(events);

        var report = await _service.GetUserActivityReportAsync("user-1", "7d");

        Assert.Equal(2, report.TotalEvents);
        Assert.False(report.ActionCounts.ContainsKey("read"));
        Assert.Equal(events[1].Timestamp, report.FirstActivity);
        Assert.Equal(events[0].Timestamp, report.LastActivity);
        Assert.Equal(new[] { "create", "delete" }, report.RecentEvents.Select(e => e.Action));
    }

    [Fact]
    public async Task GetUserActivityReportAsync_ShouldCapRecentEventsAtTen()
    {
        var events = Enumerable.Range(0, 15)
            .Select(i => CreateEvent("user-1", "read", DateTime.UtcNow.AddMinutes(-i)))
            .ToList();

        _mockRepository.Setup(r => r.GetAllUserEventsAsync("user-1")).ReturnsAsync(events);

        var report = await _service.GetUserActivityReportAsync("user-1", "day");

        Assert.Equal(15, report.TotalEvents);
        Assert.Equal(10, report.RecentEvents.Count);
    }

    [Fact]
    public async Task GetUserActivityReportAsync_WithNoEvents_ShouldReturnEmptyActivityWindow()
    {
        _mockRepository.Setup(r => r.GetAllUserEventsAsync("ghost")).ReturnsAsync(new List<AuditEvent>());

        var report = await _service.GetUserActivityReportAsync("ghost", "year");

        Assert.Equal(0, report.TotalEvents);
        Assert.Null(report.FirstActivity);
        Assert.Null(report.LastActivity);
        Assert.Empty(report.RecentEvents);
    }

    private static AuditEvent CreateEvent(string userId, string action, DateTime? timestamp = null) => new()
    {
        Id = Guid.NewGuid().ToString(),
        UserId = userId,
        Action = action,
        ResourceType = "document",
        ResourceId = "doc-1",
        Timestamp = timestamp ?? DateTime.UtcNow.AddMinutes(-1),
    };
}
