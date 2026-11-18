using System.Text.Json;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Http.Features;
using Microsoft.Extensions.Logging.Abstractions;
using OtterWorks.AuditService.Middleware;

namespace AuditService.Tests;

public class MiddlewareTests
{
    private sealed class StartedResponseFeature : HttpResponseFeature
    {
        public override bool HasStarted => true;
    }

    private static DefaultHttpContext NewContext()
    {
        var ctx = new DefaultHttpContext();
        ctx.Request.Method = "GET";
        ctx.Request.Path = "/api/v1/audit/events";
        ctx.Response.Body = new MemoryStream();
        ctx.TraceIdentifier = "trace-123";
        return ctx;
    }

    [Fact]
    public async Task ErrorHandling_PassesThroughOnSuccess()
    {
        var ctx = NewContext();
        var mw = new ErrorHandlingMiddleware(c => { c.Response.StatusCode = 204; return Task.CompletedTask; },
            NullLogger<ErrorHandlingMiddleware>.Instance);

        await mw.InvokeAsync(ctx);

        Assert.Equal(204, ctx.Response.StatusCode);
        Assert.Equal(0, ctx.Response.Body.Length);
    }

    [Fact]
    public async Task ErrorHandling_WritesJson500OnException()
    {
        var ctx = NewContext();
        var mw = new ErrorHandlingMiddleware(_ => throw new InvalidOperationException("boom"),
            NullLogger<ErrorHandlingMiddleware>.Instance);

        await mw.InvokeAsync(ctx);

        Assert.Equal(500, ctx.Response.StatusCode);
        Assert.Equal("application/json", ctx.Response.ContentType);
        ctx.Response.Body.Position = 0;
        using var doc = await JsonDocument.ParseAsync(ctx.Response.Body);
        Assert.Equal("An internal server error occurred.", doc.RootElement.GetProperty("error").GetString());
        Assert.Equal("trace-123", doc.RootElement.GetProperty("traceId").GetString());
        Assert.DoesNotContain("boom", doc.RootElement.GetRawText());
    }

    [Fact]
    public async Task ErrorHandling_RethrowsWhenResponseAlreadyStarted()
    {
        var ctx = NewContext();
        ctx.Features.Set<IHttpResponseFeature>(new StartedResponseFeature());
        var mw = new ErrorHandlingMiddleware(_ => throw new InvalidOperationException("late"),
            NullLogger<ErrorHandlingMiddleware>.Instance);

        var ex = await Assert.ThrowsAsync<InvalidOperationException>(() => mw.InvokeAsync(ctx));
        Assert.Equal("late", ex.Message);
    }

    [Fact]
    public async Task RequestLogging_InvokesNext()
    {
        var ctx = NewContext();
        var called = false;
        var mw = new RequestLoggingMiddleware(c => { called = true; c.Response.StatusCode = 200; return Task.CompletedTask; },
            NullLogger<RequestLoggingMiddleware>.Instance);

        await mw.InvokeAsync(ctx);

        Assert.True(called);
        Assert.Equal(200, ctx.Response.StatusCode);
    }

    [Fact]
    public async Task RequestLogging_RethrowsExceptions()
    {
        var ctx = NewContext();
        var mw = new RequestLoggingMiddleware(_ => throw new TimeoutException("slow"),
            NullLogger<RequestLoggingMiddleware>.Instance);

        await Assert.ThrowsAsync<TimeoutException>(() => mw.InvokeAsync(ctx));
    }
}
