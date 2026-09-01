using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Logging;
using Moq;
using OtterWorks.AuditService.Middleware;

namespace AuditService.Tests;

public class RequestLoggingMiddlewareTests
{
    private readonly Mock<ILogger<RequestLoggingMiddleware>> _logger = new();

    [Fact]
    public async Task InvokeAsync_LogsMethodPathAndStatus_WhenNextSucceeds()
    {
        var middleware = new RequestLoggingMiddleware(
            context =>
            {
                context.Response.StatusCode = StatusCodes.Status201Created;
                return Task.CompletedTask;
            },
            _logger.Object);

        var context = new DefaultHttpContext();
        context.Request.Method = "POST";
        context.Request.Path = "/api/v1/audit/events";

        await middleware.InvokeAsync(context);

        Assert.Equal(StatusCodes.Status201Created, context.Response.StatusCode);
        VerifyLogged(LogLevel.Information, "HTTP POST /api/v1/audit/events responded 201", Times.Once());
    }

    [Fact]
    public async Task InvokeAsync_LogsAndRethrows_WhenNextThrows()
    {
        var middleware = new RequestLoggingMiddleware(
            _ => throw new InvalidOperationException("downstream failed"),
            _logger.Object);

        var context = new DefaultHttpContext();
        context.Request.Method = "GET";
        context.Request.Path = "/api/v1/audit/events";

        var exception = await Assert.ThrowsAsync<InvalidOperationException>(() => middleware.InvokeAsync(context));

        Assert.Equal("downstream failed", exception.Message);
        VerifyLogged(LogLevel.Error, "HTTP GET /api/v1/audit/events failed after", Times.Once());
        VerifyLogged(LogLevel.Information, "responded", Times.Never());
    }

    private void VerifyLogged(LogLevel level, string messageFragment, Times times) =>
        _logger.Verify(
            l => l.Log(
                level,
                It.IsAny<EventId>(),
                It.Is<It.IsAnyType>((state, _) => state.ToString()!.Contains(messageFragment)),
                It.IsAny<Exception?>(),
                It.IsAny<Func<It.IsAnyType, Exception?, string>>()),
            times);
}
