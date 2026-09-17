using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Moq;
using OtterWorks.AuditService.Config;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

/// <summary>
/// Covers the period parser aliases and the suspicious-activity detection branch of the
/// compliance report, neither of which the original suite exercised.
/// </summary>
public class AuditServiceReportPeriodTests
{
    private readonly Mock<IAuditRepository> _repository = new();
    private readonly Mock<IAuditArchiver> _archiver = new();
    private readonly Mock<ILogger<OtterWorks.AuditService.Services.AuditService>> _logger = new();
    private readonly OtterWorks.AuditService.Services.AuditService _service;

    public AuditServiceReportPeriodTests()
    {
        _service = new OtterWorks.AuditService.Services.AuditService(
            _repository.Object,
            _archiver.Object,
            Options.Create(new AwsSettings { ArchiveAfterDays = 90 }),
            _logger.Object);
    }

    [Theory]
    [InlineData("day", 1)]
    [InlineData("24h", 1)]
    [InlineData("week", 7)]
    [InlineData("7d", 7)]
    [InlineData("month", 30)]
    [InlineData("30d", 30)]
    [InlineData("QUARTER", 90)]
    [InlineData("90d", 90)]
    [InlineData("year", 365)]
    [InlineData("365d", 365)]
    [InlineData("nonsense", 30)]
    public async Task GetComplianceReportAsync_TranslatesPeriodIntoADateRange(string period, int expectedDays)
    {
        DateTime capturedFrom = default;
        DateTime capturedTo = default;
        _repository
            .Setup(r => r.GetEventsByDateRangeAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>()))
            .Callback<DateTime, DateTime>((from, to) => (capturedFrom, capturedTo) = (from, to))
            .ReturnsAsync(new List<AuditEvent>());

        var report = await _service.GetComplianceReportAsync(period);

        Assert.Equal(period, report.Period);
        Assert.Equal(0, report.TotalEvents);
        Assert.Empty(report.SuspiciousActivities);
        Assert.Equal(expectedDays, Math.Round((capturedTo - capturedFrom).TotalDays));
    }

    [Fact]
    public async Task GetComplianceReportAsync_FlagsUsersAboveTheSuspiciousThreshold()
    {
        var events = Events("noisy-user", 500)
            .Concat(Enumerable.Range(1, 9).SelectMany(i => Events($"quiet-user-{i}", 1)))
            .ToList();
        _repository
            .Setup(r => r.GetEventsByDateRangeAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>()))
            .ReturnsAsync(events);

        var report = await _service.GetComplianceReportAsync("7d");

        Assert.Equal(509, report.TotalEvents);
        Assert.Equal(10, report.UniqueUsers);
        var suspicious = Assert.Single(report.SuspiciousActivities);
        Assert.Equal("noisy-user", suspicious.UserId);
        Assert.Equal(500, suspicious.EventCount);
        Assert.Equal("Unusually high activity: 500 events (threshold: 153)", suspicious.Reason);
        Assert.Equal(509, report.ActionBreakdown["read"]);
        Assert.Equal(509, report.ResourceTypeBreakdown["file"]);
    }

    [Fact]
    public async Task GetUserActivityReportAsync_IgnoresEventsOutsideThePeriod()
    {
        var inside = new AuditEvent
        {
            Id = "evt-in",
            UserId = "user-1",
            Action = "read",
            ResourceType = "file",
            Timestamp = DateTime.UtcNow.AddHours(-2),
        };
        var outside = new AuditEvent
        {
            Id = "evt-out",
            UserId = "user-1",
            Action = "delete",
            ResourceType = "file",
            Timestamp = DateTime.UtcNow.AddDays(-10),
        };
        _repository
            .Setup(r => r.GetAllUserEventsAsync("user-1"))
            .ReturnsAsync(new List<AuditEvent> { inside, outside });

        var report = await _service.GetUserActivityReportAsync("user-1", "24h");

        Assert.Equal(1, report.TotalEvents);
        Assert.Equal("evt-in", Assert.Single(report.RecentEvents).Id);
        Assert.Equal(1, report.ActionCounts["read"]);
        Assert.False(report.ActionCounts.ContainsKey("delete"));
        Assert.Equal(inside.Timestamp, report.FirstActivity);
        Assert.Equal(inside.Timestamp, report.LastActivity);
    }

    private static IEnumerable<AuditEvent> Events(string userId, int count) =>
        Enumerable.Range(0, count).Select(i => new AuditEvent
        {
            Id = $"{userId}-{i}",
            UserId = userId,
            Action = "read",
            ResourceType = "file",
            ResourceId = $"file-{i}",
            Timestamp = DateTime.UtcNow.AddMinutes(-i),
        });
}
