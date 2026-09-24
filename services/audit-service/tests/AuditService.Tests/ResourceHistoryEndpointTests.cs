using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Http.HttpResults;
using Moq;
using OtterWorks.AuditService.Controllers;
using OtterWorks.AuditService.Models;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

public class ResourceHistoryEndpointTests
{
    private readonly Mock<IAuditService> _auditService = new();
    private readonly Mock<IResourceAccessAuthorizer> _authorizer = new();

    private static HttpContext ContextFor(string? userId)
    {
        var context = new DefaultHttpContext();
        if (userId is not null)
        {
            context.Request.Headers["X-User-ID"] = userId;
        }

        return context;
    }

    [Fact]
    public async Task GetResourceHistory_ShouldReturn403_WhenUserHasNoAccess()
    {
        _authorizer
            .Setup(a => a.EvaluateAsync("file-1", "user-outsider", It.IsAny<CancellationToken>()))
            .ReturnsAsync(ResourceAccessDecision.Deny);

        var result = await AuditController.GetResourceHistory(
            "file-1", null, null, ContextFor("user-outsider"), _auditService.Object, _authorizer.Object);

        var json = Assert.IsAssignableFrom<IStatusCodeHttpResult>(result);
        Assert.Equal(StatusCodes.Status403Forbidden, json.StatusCode);
        _auditService.Verify(
            s => s.GetResourceHistoryAsync(It.IsAny<string>(), It.IsAny<int>(), It.IsAny<int>()),
            Times.Never);
    }

    [Fact]
    public async Task GetResourceHistory_ShouldReturnHistory_WhenUserHasAccess()
    {
        var history = new ResourceHistory { ResourceId = "file-1", TotalEvents = 1, Page = 2, PageSize = 5 };

        _authorizer
            .Setup(a => a.EvaluateAsync("file-1", "user-owner", It.IsAny<CancellationToken>()))
            .ReturnsAsync(ResourceAccessDecision.Allow);
        _auditService
            .Setup(s => s.GetResourceHistoryAsync("file-1", 2, 5))
            .ReturnsAsync(history);

        var result = await AuditController.GetResourceHistory(
            "file-1", 2, 5, ContextFor("user-owner"), _auditService.Object, _authorizer.Object);

        var ok = Assert.IsType<Ok<ResourceHistory>>(result);
        Assert.Same(history, ok.Value);
    }

    [Fact]
    public async Task GetResourceHistory_ShouldReturn403_WhenFileIsGoneButHistoryIsFileHistory()
    {
        _authorizer
            .Setup(a => a.EvaluateAsync("file-gone", "user-anyone", It.IsAny<CancellationToken>()))
            .ReturnsAsync(ResourceAccessDecision.Unknown);
        _auditService
            .Setup(s => s.GetResourceHistoryAsync("file-gone", 1, 20))
            .ReturnsAsync(new ResourceHistory { ResourceId = "file-gone", HasFileEvents = true });

        var result = await AuditController.GetResourceHistory(
            "file-gone", null, null, ContextFor("user-anyone"), _auditService.Object, _authorizer.Object);

        var json = Assert.IsAssignableFrom<IStatusCodeHttpResult>(result);
        Assert.Equal(StatusCodes.Status403Forbidden, json.StatusCode);
    }

    [Fact]
    public async Task GetResourceHistory_ShouldReturnHistory_ForNonFileResources()
    {
        var history = new ResourceHistory { ResourceId = "doc-1" };

        _authorizer
            .Setup(a => a.EvaluateAsync("doc-1", "user-anyone", It.IsAny<CancellationToken>()))
            .ReturnsAsync(ResourceAccessDecision.Unknown);
        _auditService
            .Setup(s => s.GetResourceHistoryAsync("doc-1", 1, 20))
            .ReturnsAsync(history);

        var result = await AuditController.GetResourceHistory(
            "doc-1", null, null, ContextFor("user-anyone"), _auditService.Object, _authorizer.Object);

        var ok = Assert.IsType<Ok<ResourceHistory>>(result);
        Assert.Same(history, ok.Value);
    }
}
