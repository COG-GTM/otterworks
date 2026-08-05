using System.Text.Json;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Http.Features;
using Microsoft.Extensions.Logging;
using Moq;
using OtterWorks.AuditService.Middleware;

namespace AuditService.Tests;

public class ErrorHandlingMiddlewareTests
{
    private readonly Mock<ILogger<ErrorHandlingMiddleware>> _mockLogger;

    public ErrorHandlingMiddlewareTests()
    {
        _mockLogger = new Mock<ILogger<ErrorHandlingMiddleware>>();
    }

    [Fact]
    public async Task InvokeAsync_WhenNextSucceeds_ShouldLeaveResponseUntouched()
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

        var context = CreateContext(out var body);

        await middleware.InvokeAsync(context);

        Assert.True(nextCalled);
        Assert.Equal(204, context.Response.StatusCode);
        Assert.Equal(0, body.Length);
    }

    [Fact]
    public async Task InvokeAsync_WhenNextThrows_ShouldReturn500ProblemJson()
    {
        var middleware = new ErrorHandlingMiddleware(
            _ => throw new InvalidOperationException("boom"),
            _mockLogger.Object);

        var context = CreateContext(out var body);
        context.TraceIdentifier = "trace-42";

        await middleware.InvokeAsync(context);

        Assert.Equal(500, context.Response.StatusCode);
        Assert.Equal("application/json", context.Response.ContentType);

        using var document = JsonDocument.Parse(ReadBody(body));
        Assert.Equal("An internal server error occurred.", document.RootElement.GetProperty("error").GetString());
        Assert.Equal("trace-42", document.RootElement.GetProperty("traceId").GetString());
    }

    [Fact]
    public async Task InvokeAsync_WhenNextThrows_ShouldNotLeakExceptionDetails()
    {
        var middleware = new ErrorHandlingMiddleware(
            _ => throw new InvalidOperationException("connection string secret=hunter2"),
            _mockLogger.Object);

        var context = CreateContext(out var body);

        await middleware.InvokeAsync(context);

        var payload = ReadBody(body);
        Assert.DoesNotContain("hunter2", payload);
        Assert.DoesNotContain("InvalidOperationException", payload);
    }

    [Fact]
    public async Task InvokeAsync_WhenResponseAlreadyStarted_ShouldRethrow()
    {
        var middleware = new ErrorHandlingMiddleware(
            _ => throw new InvalidOperationException("too late"),
            _mockLogger.Object);

        var context = CreateContext(out var body, responseStarted: true);

        var ex = await Assert.ThrowsAsync<InvalidOperationException>(() => middleware.InvokeAsync(context));

        Assert.Equal("too late", ex.Message);
        Assert.Equal(0, body.Length);
    }

    private static DefaultHttpContext CreateContext(out MemoryStream body, bool responseStarted = false)
    {
        body = new MemoryStream();

        var features = new FeatureCollection();
        features.Set<IHttpRequestFeature>(new HttpRequestFeature { Method = "POST", Path = "/api/v1/audit/events" });
        features.Set<IHttpResponseFeature>(responseStarted ? new StartedResponseFeature() : new HttpResponseFeature());
        features.Set<IHttpResponseBodyFeature>(new StreamResponseBodyFeature(body));

        return new DefaultHttpContext(features);
    }

    private static string ReadBody(MemoryStream body)
    {
        body.Position = 0;
        using var reader = new StreamReader(body, leaveOpen: true);
        return reader.ReadToEnd();
    }

    private sealed class StartedResponseFeature : HttpResponseFeature
    {
        public override bool HasStarted => true;
    }
}
