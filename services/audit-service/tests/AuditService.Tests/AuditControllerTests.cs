using System.Net;
using Microsoft.AspNetCore.Http;
using Moq;
using OtterWorks.AuditService.Controllers;
using OtterWorks.AuditService.Models;
using OtterWorks.AuditService.Security;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

public class AuditControllerTests
{
    private readonly Mock<IAuditService> _mockService = new();

    private static DefaultHttpContext Context(string? userId = null, string? roles = null)
    {
        var context = new DefaultHttpContext();
        if (userId is not null)
            context.Request.Headers[CallerIdentity.UserIdHeader] = userId;
        if (roles is not null)
            context.Request.Headers[CallerIdentity.RolesHeader] = roles;
        return context;
    }

    private static int? StatusOf(IResult result) => (result as IStatusCodeHttpResult)?.StatusCode;

    private static AuditEventRequest Body(string userId = "") => new()
    {
        UserId = userId,
        Action = "delete",
        ResourceType = "document",
        ResourceId = "doc-1",
        Details = new Dictionary<string, string> { ["k"] = "v" },
        IpAddress = "6.6.6.6",
        UserAgent = "SpoofedAgent/1.0",
    };

    private void CaptureRecorded(Action<AuditEventRequest> capture)
    {
        _mockService
            .Setup(s => s.RecordEventAsync(It.IsAny<AuditEventRequest>()))
            .Callback(capture)
            .ReturnsAsync((AuditEventRequest r) => new AuditEventResponse { Id = "evt-1", UserId = r.UserId });
    }

    [Fact]
    public async Task RecordEvent_WithoutGatewayIdentity_Returns401()
    {
        var result = await AuditController.RecordEvent(Body("victim"), Context(), _mockService.Object);

        Assert.Equal(StatusCodes.Status401Unauthorized, StatusOf(result));
        _mockService.Verify(s => s.RecordEventAsync(It.IsAny<AuditEventRequest>()), Times.Never);
    }

    [Fact]
    public async Task RecordEvent_WithBodyUserIdForAnotherUser_Returns403()
    {
        var result = await AuditController.RecordEvent(Body("victim"), Context("attacker"), _mockService.Object);

        Assert.Equal(StatusCodes.Status403Forbidden, StatusOf(result));
        _mockService.Verify(s => s.RecordEventAsync(It.IsAny<AuditEventRequest>()), Times.Never);
    }

    [Theory]
    [InlineData("")]
    [InlineData("user-1")]
    public async Task RecordEvent_AttributesEventToAuthenticatedCaller(string bodyUserId)
    {
        AuditEventRequest? recorded = null;
        CaptureRecorded(r => recorded = r);

        var result = await AuditController.RecordEvent(Body(bodyUserId), Context("user-1"), _mockService.Object);

        Assert.Equal(StatusCodes.Status201Created, StatusOf(result));
        Assert.NotNull(recorded);
        Assert.Equal("user-1", recorded!.UserId);
        Assert.Equal("delete", recorded.Action);
        Assert.Equal("doc-1", recorded.ResourceId);
        Assert.Equal("v", recorded.Details!["k"]);
    }

    [Fact]
    public async Task RecordEvent_IgnoresBodyNetworkMetadataAndUsesRequestContext()
    {
        AuditEventRequest? recorded = null;
        CaptureRecorded(r => recorded = r);
        var context = Context("user-1");
        context.Connection.RemoteIpAddress = IPAddress.Parse("10.1.2.3");
        context.Request.Headers.UserAgent = "RealBrowser/2.0";

        await AuditController.RecordEvent(Body("user-1"), context, _mockService.Object);

        Assert.Equal("10.1.2.3", recorded!.IpAddress);
        Assert.Equal("RealBrowser/2.0", recorded.UserAgent);
    }

    [Fact]
    public async Task RecordEvent_UsesProxyAppendedForwardedForEntryNotClientSupplied()
    {
        AuditEventRequest? recorded = null;
        CaptureRecorded(r => recorded = r);
        var context = Context("user-1");
        context.Connection.RemoteIpAddress = IPAddress.Parse("10.0.0.5");
        context.Request.Headers["X-Forwarded-For"] = "1.2.3.4, 203.0.113.9";

        await AuditController.RecordEvent(Body(), context, _mockService.Object);

        Assert.Equal("203.0.113.9", recorded!.IpAddress);
    }

    [Fact]
    public async Task RecordEvent_WithMissingRequiredFields_Returns400()
    {
        var body = Body();
        body.Action = "";

        var result = await AuditController.RecordEvent(body, Context("user-1"), _mockService.Object);

        Assert.Equal(StatusCodes.Status400BadRequest, StatusOf(result));
        _mockService.Verify(s => s.RecordEventAsync(It.IsAny<AuditEventRequest>()), Times.Never);
    }

    [Fact]
    public async Task ArchiveOldEvents_WithoutGatewayIdentity_Returns401()
    {
        var result = await AuditController.ArchiveOldEvents(Context(), _mockService.Object);

        Assert.Equal(StatusCodes.Status401Unauthorized, StatusOf(result));
        _mockService.Verify(s => s.ArchiveOldEventsAsync(), Times.Never);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("USER")]
    [InlineData("USER,EDITOR")]
    [InlineData("ADMINISTRATOR")]
    public async Task ArchiveOldEvents_ForNonAdmin_Returns403AndDoesNotArchive(string? roles)
    {
        var result = await AuditController.ArchiveOldEvents(Context("user-1", roles), _mockService.Object);

        Assert.Equal(StatusCodes.Status403Forbidden, StatusOf(result));
        _mockService.Verify(s => s.ArchiveOldEventsAsync(), Times.Never);
    }

    [Theory]
    [InlineData("ADMIN")]
    [InlineData("USER, admin")]
    public async Task ArchiveOldEvents_ForAdmin_Archives(string roles)
    {
        _mockService.Setup(s => s.ArchiveOldEventsAsync()).ReturnsAsync(new ArchiveResult { ArchivedCount = 3 });

        var result = await AuditController.ArchiveOldEvents(Context("admin-1", roles), _mockService.Object);

        Assert.Equal(StatusCodes.Status200OK, StatusOf(result));
        _mockService.Verify(s => s.ArchiveOldEventsAsync(), Times.Once);
    }
}
