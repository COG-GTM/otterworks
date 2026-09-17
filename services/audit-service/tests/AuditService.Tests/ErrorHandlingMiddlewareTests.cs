using System.Text.Json;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Http.Features;
using Microsoft.Extensions.Logging;
using Moq;
using OtterWorks.AuditService.Middleware;

namespace AuditService.Tests;

public class ErrorHandlingMiddlewareTests
{
    private readonly Mock<ILogger<ErrorHandlingMiddleware>> _logger = new();

    [Fact]
    public async Task InvokeAsync_LeavesResponseUntouched_WhenNextSucceeds()
    {
        var nextCalled = false;
        var middleware = new ErrorHandlingMiddleware(
            context =>
            {
                nextCalled = true;
                context.Response.StatusCode = StatusCodes.Status204NoContent;
                return Task.CompletedTask;
            },
            _logger.Object);

        var context = new DefaultHttpContext();

        await middleware.InvokeAsync(context);

        Assert.True(nextCalled);
        Assert.Equal(StatusCodes.Status204NoContent, context.Response.StatusCode);
        VerifyLogged(LogLevel.Error, Times.Never());
    }

    [Fact]
    public async Task InvokeAsync_Writes500JsonWithTraceId_WhenNextThrows()
    {
        var middleware = new ErrorHandlingMiddleware(
            _ => throw new InvalidOperationException("boom"),
            _logger.Object);

        var context = new DefaultHttpContext();
        context.Request.Method = "POST";
        context.Request.Path = "/api/v1/audit/events";
        context.TraceIdentifier = "trace-42";
        context.Response.Body = new MemoryStream();

        await middleware.InvokeAsync(context);

        Assert.Equal(StatusCodes.Status500InternalServerError, context.Response.StatusCode);
        Assert.Equal("application/json", context.Response.ContentType);

        context.Response.Body.Position = 0;
        using var document = JsonDocument.Parse(context.Response.Body);
        Assert.Equal("An internal server error occurred.", document.RootElement.GetProperty("error").GetString());
        Assert.Equal("trace-42", document.RootElement.GetProperty("traceId").GetString());
        VerifyLogged(LogLevel.Error, Times.Once());
    }

    [Fact]
    public async Task InvokeAsync_Rethrows_WhenResponseHasAlreadyStarted()
    {
        var middleware = new ErrorHandlingMiddleware(
            _ => throw new InvalidOperationException("too late"),
            _logger.Object);

        var features = new FeatureCollection();
        features.Set<IHttpRequestFeature>(new HttpRequestFeature { Method = "GET", Path = "/api/v1/audit/events" });
        features.Set<IHttpResponseFeature>(new StartedResponseFeature());
        features.Set<IHttpResponseBodyFeature>(new StreamResponseBodyFeature(new MemoryStream()));
        var context = new DefaultHttpContext(features);

        var exception = await Assert.ThrowsAsync<InvalidOperationException>(() => middleware.InvokeAsync(context));

        Assert.Equal("too late", exception.Message);
        Assert.Equal(StatusCodes.Status200OK, context.Response.StatusCode);
        VerifyLogged(LogLevel.Error, Times.Once());
        VerifyLogged(LogLevel.Warning, Times.Once());
    }

    private void VerifyLogged(LogLevel level, Times times) =>
        _logger.Verify(
            l => l.Log(
                level,
                It.IsAny<EventId>(),
                It.IsAny<It.IsAnyType>(),
                It.IsAny<Exception?>(),
                It.IsAny<Func<It.IsAnyType, Exception?, string>>()),
            times);

    private sealed class StartedResponseFeature : IHttpResponseFeature
    {
        public Stream Body { get; set; } = Stream.Null;

        public bool HasStarted => true;

        public IHeaderDictionary Headers { get; set; } = new HeaderDictionary();

        public string? ReasonPhrase { get; set; }

        public int StatusCode { get; set; } = StatusCodes.Status200OK;

        public void OnCompleted(Func<object, Task> callback, object state)
        {
        }

        public void OnStarting(Func<object, Task> callback, object state)
        {
        }
    }
}
