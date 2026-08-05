using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Logging;
using Moq;
using OtterWorks.AuditService.Middleware;

namespace AuditService.Tests;

public class RequestLoggingMiddlewareTests
{
    private readonly Mock<ILogger<RequestLoggingMiddleware>> _mockLogger;

    public RequestLoggingMiddlewareTests()
    {
        _mockLogger = new Mock<ILogger<RequestLoggingMiddleware>>();
    }

    [Fact]
    public async Task InvokeAsync_WhenNextSucceeds_ShouldLogCompletedRequest()
    {
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

        Assert.Equal(201, context.Response.StatusCode);
        VerifyLogged(LogLevel.Information, "HTTP POST /api/v1/audit/events responded 201");
    }

    [Fact]
    public async Task InvokeAsync_WhenNextThrows_ShouldLogFailureAndRethrow()
    {
        var middleware = new RequestLoggingMiddleware(
            _ => throw new TimeoutException("downstream timeout"),
            _mockLogger.Object);

        var context = new DefaultHttpContext();
        context.Request.Method = "GET";
        context.Request.Path = "/api/v1/audit/events";

        var ex = await Assert.ThrowsAsync<TimeoutException>(() => middleware.InvokeAsync(context));

        Assert.Equal("downstream timeout", ex.Message);
        VerifyLogged(LogLevel.Error, "HTTP GET /api/v1/audit/events failed");
    }

    private void VerifyLogged(LogLevel level, string expectedPrefix)
    {
        _mockLogger.Verify(
            l => l.Log(
                level,
                It.IsAny<EventId>(),
                It.Is<It.IsAnyType>((state, _) => state.ToString()!.StartsWith(expectedPrefix, StringComparison.Ordinal)),
                It.IsAny<Exception?>(),
                It.IsAny<Func<It.IsAnyType, Exception?, string>>()),
            Times.Once);
    }
}
