using System.Text.Json;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Http.Features;
using Microsoft.Extensions.Logging;
using Moq;
using OtterWorks.AuditService.Middleware;

namespace AuditService.Tests;

public class ErrorHandlingMiddlewareTests
{
    private readonly Mock<ILogger<ErrorHandlingMiddleware>> _mockLogger = new();

    [Fact]
    public async Task InvokeAsync_ShouldCallNext_WhenNoExceptionIsThrown()
    {
        var called = false;
        var middleware = new ErrorHandlingMiddleware(
            _ =>
            {
                called = true;
                return Task.CompletedTask;
            },
            _mockLogger.Object);

        var context = new DefaultHttpContext();

        await middleware.InvokeAsync(context);

        Assert.True(called);
        Assert.Equal(200, context.Response.StatusCode);
    }

    [Fact]
    public async Task InvokeAsync_ShouldReturn500Json_WhenNextThrows()
    {
        var middleware = new ErrorHandlingMiddleware(
            _ => throw new InvalidOperationException("boom"),
            _mockLogger.Object);

        var context = new DefaultHttpContext();
        context.Request.Method = "POST";
        context.Request.Path = "/api/v1/audit/events";
        context.TraceIdentifier = "trace-1";
        context.Response.Body = new MemoryStream();

        await middleware.InvokeAsync(context);

        Assert.Equal(500, context.Response.StatusCode);
        Assert.Equal("application/json", context.Response.ContentType);

        context.Response.Body.Position = 0;
        using var document = JsonDocument.Parse(context.Response.Body);
        Assert.Equal("An internal server error occurred.", document.RootElement.GetProperty("error").GetString());
        Assert.Equal("trace-1", document.RootElement.GetProperty("traceId").GetString());
    }

    [Fact]
    public async Task InvokeAsync_ShouldRethrow_WhenResponseHasAlreadyStarted()
    {
        var middleware = new ErrorHandlingMiddleware(
            async context =>
            {
                await context.Response.WriteAsync("partial");
                await context.Response.Body.FlushAsync();
                throw new InvalidOperationException("boom");
            },
            _mockLogger.Object);

        var context = new DefaultHttpContext();
        context.Features.Set<IHttpResponseFeature>(new StartedResponseFeature());
        context.Response.Body = new MemoryStream();

        await Assert.ThrowsAsync<InvalidOperationException>(() => middleware.InvokeAsync(context));

        Assert.NotEqual(500, context.Response.StatusCode);
    }

    private sealed class StartedResponseFeature : IHttpResponseFeature
    {
        public Stream Body { get; set; } = Stream.Null;

        public bool HasStarted => true;

        public IHeaderDictionary Headers { get; set; } = new HeaderDictionary();

        public string? ReasonPhrase { get; set; }

        public int StatusCode { get; set; } = 200;

        public void OnCompleted(Func<object, Task> callback, object state)
        {
        }

        public void OnStarting(Func<object, Task> callback, object state)
        {
        }
    }
}
