using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Moq;
using OtterWorks.AuditService.Config;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

public class AuditServiceReportTests
{
    private readonly Mock<IAuditRepository> _repository = new();
    private readonly OtterWorks.AuditService.Services.AuditService _service;

    public AuditServiceReportTests()
    {
        _service = new OtterWorks.AuditService.Services.AuditService(
            _repository.Object,
            new Mock<IAuditArchiver>().Object,
            Options.Create(new AwsSettings()),
            NullLogger<OtterWorks.AuditService.Services.AuditService>.Instance);
    }

    private static List<AuditEvent> EventsFor(string userId, int count) =>
        Enumerable.Range(0, count).Select(i => new AuditEvent
        {
            Id = $"{userId}-{i}",
            UserId = userId,
            Action = "read",
            ResourceType = "file",
            ResourceId = $"f{i}",
            Timestamp = DateTime.UtcNow.AddMinutes(-i),
        }).ToList();

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
    [InlineData("bogus", 30)]
    public async Task ComplianceReport_ParsesPeriod(string period, int expectedDays)
    {
        DateTime from = default, to = default;
        _repository.Setup(r => r.GetEventsByDateRangeAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>()))
            .Callback<DateTime, DateTime>((f, t) => { from = f; to = t; })
            .ReturnsAsync(new List<AuditEvent>());

        var report = await _service.GetComplianceReportAsync(period);

        Assert.Equal(period, report.Period);
        Assert.Equal(expectedDays, Math.Round((to - from).TotalDays));
        Assert.True((DateTime.UtcNow - to).TotalSeconds < 5);
    }

    [Fact]
    public async Task ComplianceReport_WithNoEvents_HasNoSuspiciousActivity()
    {
        _repository.Setup(r => r.GetEventsByDateRangeAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>()))
            .ReturnsAsync(new List<AuditEvent>());

        var report = await _service.GetComplianceReportAsync("30d");

        Assert.Equal(0, report.TotalEvents);
        Assert.Equal(0, report.UniqueUsers);
        Assert.Empty(report.SuspiciousActivities);
    }

    [Fact]
    public async Task ComplianceReport_FlagsUserAboveThreshold()
    {
        var events = EventsFor("noisy", 500);
        foreach (var u in new[] { "a", "b", "c", "d" })
            events.AddRange(EventsFor(u, 1));
        _repository.Setup(r => r.GetEventsByDateRangeAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>()))
            .ReturnsAsync(events);

        var report = await _service.GetComplianceReportAsync("7d");

        Assert.Equal(504, report.TotalEvents);
        Assert.Equal(5, report.UniqueUsers);
        var flagged = Assert.Single(report.SuspiciousActivities);
        Assert.Equal("noisy", flagged.UserId);
        Assert.Equal(500, flagged.EventCount);
        Assert.Contains("500 events", flagged.Reason);
        Assert.Contains("threshold: 302", flagged.Reason);
    }

    [Fact]
    public async Task ComplianceReport_UsesFloorOf100Events()
    {
        var events = EventsFor("u1", 100);
        events.AddRange(EventsFor("u2", 1));
        events.AddRange(EventsFor("u3", 1));
        events.AddRange(EventsFor("u4", 1));
        events.AddRange(EventsFor("u5", 1));
        _repository.Setup(r => r.GetEventsByDateRangeAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>()))
            .ReturnsAsync(events);

        var report = await _service.GetComplianceReportAsync("7d");

        Assert.Empty(report.SuspiciousActivities);
    }

    [Fact]
    public async Task UserActivityReport_ExcludesEventsOutsidePeriod()
    {
        var events = new List<AuditEvent>
        {
            new() { Id = "in", UserId = "u1", Action = "read", ResourceType = "file", Timestamp = DateTime.UtcNow.AddHours(-2) },
            new() { Id = "old", UserId = "u1", Action = "delete", ResourceType = "doc", Timestamp = DateTime.UtcNow.AddDays(-3) },
        };
        _repository.Setup(r => r.GetAllUserEventsAsync("u1")).ReturnsAsync(events);

        var report = await _service.GetUserActivityReportAsync("u1", "day");

        Assert.Equal(1, report.TotalEvents);
        Assert.Equal("in", Assert.Single(report.RecentEvents).Id);
        Assert.False(report.ActionCounts.ContainsKey("delete"));
    }

    [Fact]
    public async Task UserActivityReport_WithNoEvents_HasNullActivityBounds()
    {
        _repository.Setup(r => r.GetAllUserEventsAsync("ghost")).ReturnsAsync(new List<AuditEvent>());

        var report = await _service.GetUserActivityReportAsync("ghost", "30d");

        Assert.Equal(0, report.TotalEvents);
        Assert.Null(report.FirstActivity);
        Assert.Null(report.LastActivity);
        Assert.Empty(report.RecentEvents);
    }

    [Fact]
    public async Task UserActivityReport_CapsRecentEventsAtTenNewestFirst()
    {
        _repository.Setup(r => r.GetAllUserEventsAsync("u1")).ReturnsAsync(EventsFor("u1", 15));

        var report = await _service.GetUserActivityReportAsync("u1", "30d");

        Assert.Equal(15, report.TotalEvents);
        Assert.Equal(10, report.RecentEvents.Count);
        Assert.Equal("u1-0", report.RecentEvents[0].Id);
        Assert.Equal(report.RecentEvents[0].Timestamp, report.LastActivity);
    }
}
