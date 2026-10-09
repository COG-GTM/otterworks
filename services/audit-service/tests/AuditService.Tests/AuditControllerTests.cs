using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Options;
using Moq;
using OtterWorks.AuditService.Config;
using OtterWorks.AuditService.Controllers;
using OtterWorks.AuditService.Models;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

public class AuditControllerTests
{
    private readonly Mock<IAuditService> _mockService = new();
    private readonly IOptions<AuditLimits> _limits = Options.Create(new AuditLimits { MaxExportRangeDays = 31, MaxQueryWindow = 1_000 });

    [Fact]
    public async Task ExportAuditLog_RangeOverLimit_ReturnsBadRequest()
    {
        var result = await AuditController.ExportAuditLog(
            "json", new DateTime(1, 1, 1), new DateTime(9999, 12, 31), _mockService.Object, _limits);

        Assert.Equal(StatusCodes.Status400BadRequest, StatusCode(result));
        _mockService.Verify(s => s.ExportAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>(), It.IsAny<string>()), Times.Never);
    }

    [Fact]
    public async Task ExportAuditLog_FromAfterTo_ReturnsBadRequest()
    {
        var to = DateTime.UtcNow;
        var result = await AuditController.ExportAuditLog("json", to.AddDays(1), to, _mockService.Object, _limits);

        Assert.Equal(StatusCodes.Status400BadRequest, StatusCode(result));
    }

    [Fact]
    public async Task ExportAuditLog_DefaultRange_IsAllowed()
    {
        _mockService
            .Setup(s => s.ExportAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>(), "json"))
            .ReturnsAsync(new ExportResult { Format = "json" });

        var result = await AuditController.ExportAuditLog(null, null, null, _mockService.Object, _limits);

        Assert.Equal(StatusCodes.Status200OK, StatusCode(result));
        _mockService.Verify(s => s.ExportAsync(
            It.IsAny<DateTime>(), It.IsAny<DateTime>(), "json"), Times.Once);
    }

    [Fact]
    public async Task QueryEvents_PageBeyondWindow_ReturnsBadRequest()
    {
        var result = await AuditController.QueryEvents(null, null, null, null, null, null, 11, 100, _mockService.Object, _limits);

        Assert.Equal(StatusCodes.Status400BadRequest, StatusCode(result));
        _mockService.Verify(s => s.QueryEventsAsync(
            It.IsAny<string?>(), It.IsAny<string?>(), It.IsAny<string?>(), It.IsAny<string?>(),
            It.IsAny<DateTime?>(), It.IsAny<DateTime?>(), It.IsAny<int>(), It.IsAny<int>()), Times.Never);
    }

    [Fact]
    public async Task QueryEvents_WithinWindow_DelegatesWithClampedSize()
    {
        _mockService
            .Setup(s => s.QueryEventsAsync(null, null, null, null, null, null, 10, 100))
            .ReturnsAsync(new AuditEventPage());

        var result = await AuditController.QueryEvents(null, null, null, null, null, null, 10, 500, _mockService.Object, _limits);

        Assert.Equal(StatusCodes.Status200OK, StatusCode(result));
    }

    [Fact]
    public async Task RecordEvent_OversizedDetails_ReturnsBadRequest()
    {
        var request = new AuditEventRequest
        {
            UserId = "u1",
            Action = "create",
            ResourceType = "doc",
            ResourceId = "d1",
            Details = Enumerable.Range(1, 100).ToDictionary(i => $"k{i}", _ => "v"),
        };

        var result = await AuditController.RecordEvent(request, _mockService.Object, _limits);

        Assert.Equal(StatusCodes.Status400BadRequest, StatusCode(result));
        _mockService.Verify(s => s.RecordEventAsync(It.IsAny<AuditEventRequest>()), Times.Never);
    }

    private static int? StatusCode(IResult result) => (result as IStatusCodeHttpResult)?.StatusCode;
}
