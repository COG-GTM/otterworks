using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Logging;
using Moq;
using OtterWorks.AuditService.Middleware;

namespace AuditService.Tests;

public class RequestLoggingMiddlewareTests
{
    private readonly Mock<ILogger<RequestLoggingMiddleware>> _mockLogger = new();

    [Fact]
    public async Task InvokeAsync_ShouldLogInformation_WhenRequestSucceeds()
    {
        var middleware = new RequestLoggingMiddleware(
            context =>
            {
                context.Response.StatusCode = 201;
                return Task.CompletedTask;
            },
            _mockLogger.Object);

        var context = new DefaultHttpContext();
        context.Request.Method = "POST";
        context.Request.Path = "/api/v1/audit/events";

        await middleware.InvokeAsync(context);

        Assert.Equal(201, context.Response.StatusCode);
        VerifyLogged(LogLevel.Information);
    }

    [Fact]
    public async Task InvokeAsync_ShouldLogErrorAndRethrow_WhenRequestFails()
    {
        var middleware = new RequestLoggingMiddleware(
            _ => throw new InvalidOperationException("boom"),
            _mockLogger.Object);

        var context = new DefaultHttpContext();
        context.Request.Method = "GET";
        context.Request.Path = "/api/v1/audit/events";

        var exception = await Assert.ThrowsAsync<InvalidOperationException>(() => middleware.InvokeAsync(context));

        Assert.Equal("boom", exception.Message);
        VerifyLogged(LogLevel.Error);
    }

    private void VerifyLogged(LogLevel level) =>
        _mockLogger.Verify(
            l => l.Log(
                level,
                It.IsAny<EventId>(),
                It.IsAny<It.IsAnyType>(),
                It.IsAny<Exception?>(),
                It.IsAny<Func<It.IsAnyType, Exception?, string>>()),
            Times.Once);
}
