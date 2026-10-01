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
    public async Task InvokeAsync_ShouldPassThrough_WhenNextSucceeds()
    {
        var nextCalled = false;
        var middleware = new ErrorHandlingMiddleware(
            ctx =>
            {
                nextCalled = true;
                ctx.Response.StatusCode = 204;
                return Task.CompletedTask;
            },
            _mockLogger.Object);

        var context = new DefaultHttpContext();
        context.Response.Body = new MemoryStream();

        await middleware.InvokeAsync(context);

        Assert.True(nextCalled);
        Assert.Equal(204, context.Response.StatusCode);
        Assert.Equal(0, context.Response.Body.Length);
    }

    [Fact]
    public async Task InvokeAsync_ShouldReturn500Json_WhenNextThrows()
    {
        var middleware = new ErrorHandlingMiddleware(
            _ => throw new InvalidOperationException("boom"),
            _mockLogger.Object);

        var context = new DefaultHttpContext();
        context.TraceIdentifier = "trace-42";
        context.Request.Method = "POST";
        context.Request.Path = "/api/v1/audit/events";
        context.Response.Body = new MemoryStream();

        await middleware.InvokeAsync(context);

        Assert.Equal(500, context.Response.StatusCode);
        Assert.Equal("application/json", context.Response.ContentType);

        context.Response.Body.Position = 0;
        using var doc = JsonDocument.Parse(await new StreamReader(context.Response.Body).ReadToEndAsync());
        Assert.Equal("An internal server error occurred.", doc.RootElement.GetProperty("error").GetString());
        Assert.Equal("trace-42", doc.RootElement.GetProperty("traceId").GetString());

        _mockLogger.Verify(
            l => l.Log(
                LogLevel.Error,
                It.IsAny<EventId>(),
                It.IsAny<It.IsAnyType>(),
                It.IsAny<InvalidOperationException>(),
                It.IsAny<Func<It.IsAnyType, Exception?, string>>()),
            Times.Once);
    }

    [Fact]
    public async Task InvokeAsync_ShouldRethrow_WhenResponseAlreadyStarted()
    {
        var middleware = new ErrorHandlingMiddleware(
            async ctx =>
            {
                await ctx.Response.WriteAsync("partial");
                await ctx.Response.Body.FlushAsync();
                throw new InvalidOperationException("late failure");
            },
            _mockLogger.Object);

        var context = new DefaultHttpContext();
        context.Features.Set<IHttpResponseFeature>(new StartedResponseFeature());
        context.Response.Body = new MemoryStream();

        var ex = await Assert.ThrowsAsync<InvalidOperationException>(() => middleware.InvokeAsync(context));
        Assert.Equal("late failure", ex.Message);

        _mockLogger.Verify(
            l => l.Log(
                LogLevel.Warning,
                It.IsAny<EventId>(),
                It.IsAny<It.IsAnyType>(),
                It.IsAny<Exception>(),
                It.IsAny<Func<It.IsAnyType, Exception?, string>>()),
            Times.Once);
    }

    private sealed class StartedResponseFeature : IHttpResponseFeature
    {
        public Stream Body { get; set; } = new MemoryStream();

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
