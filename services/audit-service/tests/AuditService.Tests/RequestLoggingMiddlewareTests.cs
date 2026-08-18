using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Logging;
using Moq;
using OtterWorks.AuditService.Middleware;

namespace AuditService.Tests;

public class RequestLoggingMiddlewareTests
{
    private readonly Mock<ILogger<RequestLoggingMiddleware>> _mockLogger = new();

    [Fact]
    public async Task InvokeAsync_ShouldLogCompletedRequest_WhenNextSucceeds()
    {
        string? logged = null;
        _mockLogger
            .Setup(l => l.Log(
                LogLevel.Information,
                It.IsAny<EventId>(),
                It.IsAny<It.IsAnyType>(),
                null,
                It.IsAny<Func<It.IsAnyType, Exception?, string>>()))
            .Callback(new InvocationAction(inv => logged = inv.Arguments[2]?.ToString()));

        var middleware = new RequestLoggingMiddleware(
            ctx =>
            {
                ctx.Response.StatusCode = 201;
                return Task.CompletedTask;
            },
            _mockLogger.Object);

        var context = new DefaultHttpContext();
        context.Request.Method = "POST";
        context.Request.Path = "/api/v1/audit/events";

        await middleware.InvokeAsync(context);

        Assert.NotNull(logged);
        Assert.Contains("POST", logged);
        Assert.Contains("/api/v1/audit/events", logged);
        Assert.Contains("201", logged);
    }

    [Fact]
    public async Task InvokeAsync_ShouldLogAndRethrow_WhenNextThrows()
    {
        var middleware = new RequestLoggingMiddleware(
            _ => throw new InvalidOperationException("downstream failure"),
            _mockLogger.Object);

        var context = new DefaultHttpContext();
        context.Request.Method = "GET";
        context.Request.Path = "/api/v1/audit/events";

        var ex = await Assert.ThrowsAsync<InvalidOperationException>(() => middleware.InvokeAsync(context));
        Assert.Equal("downstream failure", ex.Message);

        _mockLogger.Verify(
            l => l.Log(
                LogLevel.Error,
                It.IsAny<EventId>(),
                It.IsAny<It.IsAnyType>(),
                It.IsAny<InvalidOperationException>(),
                It.IsAny<Func<It.IsAnyType, Exception?, string>>()),
            Times.Once);
    }
}
