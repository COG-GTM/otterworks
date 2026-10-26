using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Hosting.Server;
using Microsoft.AspNetCore.Hosting.Server.Features;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using OtterWorks.AuditService.Auth;
using OtterWorks.AuditService.Controllers;
using OtterWorks.AuditService.Models;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

public sealed class AuditAuthorizationTests : IAsyncLifetime
{
    private const string Secret = "audit-tests-jwt-secret-0123456789abcdef0123456789";
    private const string Alice = "alice-id";
    private const string Mallory = "mallory-id";
    private const string AdminUser = "admin-id";

    private readonly FakeAuditService _audit = new();
    private WebApplication _app = null!;
    private HttpClient _client = null!;

    public async Task InitializeAsync()
    {
        (_app, _client) = await StartAsync(Secret, _audit);
        _audit.Seed("evt-alice", Alice, "doc-1");
        _audit.Seed("evt-mallory", Mallory, "doc-1");
    }

    public async Task DisposeAsync() => await _app.DisposeAsync();

    public static IEnumerable<object[]> AllRoutes() => new[]
    {
        new object[] { "POST", "/api/v1/audit/events" },
        new object[] { "GET", "/api/v1/audit/events" },
        new object[] { "GET", "/api/v1/audit/events/evt-alice" },
        new object[] { "GET", $"/api/v1/audit/reports/user/{Alice}" },
        new object[] { "GET", "/api/v1/audit/resources/doc-1/history" },
        new object[] { "GET", "/api/v1/audit/reports/compliance" },
        new object[] { "GET", "/api/v1/audit/export" },
        new object[] { "POST", "/api/v1/audit/archive" },
    };

    [Theory]
    [MemberData(nameof(AllRoutes))]
    public async Task EveryRoute_RejectsAnonymousCallers(string method, string path)
    {
        var response = await SendAsync(method, path, token: null);

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        Assert.Empty(_audit.Calls);
    }

    [Theory]
    [MemberData(nameof(AllRoutes))]
    public async Task EveryRoute_RejectsTokensSignedWithAnotherSecret(string method, string path)
    {
        var forged = Jwt(Mallory, new[] { "ADMIN" }, secret: "attacker-chosen-secret-0123456789abcdef0123");

        var response = await SendAsync(method, path, forged);

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        Assert.Empty(_audit.Calls);
    }

    [Fact]
    public async Task RejectsUnsignedAlgNoneTokens()
    {
        var header = B64(JsonSerializer.SerializeToUtf8Bytes(new { alg = "none", typ = "JWT" }));
        var payload = B64(JsonSerializer.SerializeToUtf8Bytes(Claims(AdminUser, new[] { "ADMIN" }, "access", 300)));

        var response = await SendAsync("GET", "/api/v1/audit/events", $"{header}.{payload}.");

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task RejectsExpiredAccessTokens()
    {
        var response = await SendAsync("GET", "/api/v1/audit/events", Jwt(Alice, expiresInSeconds: -120));

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task RejectsRefreshTokens()
    {
        var response = await SendAsync("GET", "/api/v1/audit/events", Jwt(Alice, type: "refresh"));

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task MissingJwtSecret_FailsClosed()
    {
        var (app, client) = await StartAsync(secret: null, new FakeAuditService());
        await using var _ = app;
        client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", Jwt(Alice));

        var response = await client.GetAsync("/api/v1/audit/events");

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task QueryEvents_NonAdminWithoutFilter_IsScopedToCaller()
    {
        var response = await SendAsync("GET", "/api/v1/audit/events", Jwt(Mallory));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal(Mallory, _audit.LastQueryUserId);
        var page = await response.Content.ReadFromJsonAsync<AuditEventPage>();
        Assert.All(page!.Events, e => Assert.Equal(Mallory, e.UserId));
    }

    [Fact]
    public async Task QueryEvents_NonAdminFilteringAnotherUser_IsForbidden()
    {
        var response = await SendAsync("GET", $"/api/v1/audit/events?user_id={Alice}", Jwt(Mallory));

        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
        Assert.DoesNotContain("QueryEvents", _audit.Calls);
    }

    [Fact]
    public async Task QueryEvents_AdminCanQueryAnyUser()
    {
        var response = await SendAsync("GET", $"/api/v1/audit/events?user_id={Alice}", Jwt(AdminUser, new[] { "ADMIN" }));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal(Alice, _audit.LastQueryUserId);
    }

    [Fact]
    public async Task GetEvent_OtherUsersEvent_IsNotFound()
    {
        var response = await SendAsync("GET", "/api/v1/audit/events/evt-alice", Jwt(Mallory));

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }

    [Fact]
    public async Task GetEvent_OwnEvent_IsReturned()
    {
        var response = await SendAsync("GET", "/api/v1/audit/events/evt-alice", Jwt(Alice));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    [Fact]
    public async Task UserActivityReport_ForAnotherUser_IsForbidden()
    {
        var response = await SendAsync("GET", $"/api/v1/audit/reports/user/{Alice}", Jwt(Mallory));

        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
        Assert.DoesNotContain("GetUserActivityReport", _audit.Calls);
    }

    [Fact]
    public async Task UserActivityReport_ForSelfOrAsOwnerRole_IsAllowed()
    {
        var self = await SendAsync("GET", $"/api/v1/audit/reports/user/{Alice}", Jwt(Alice));
        var owner = await SendAsync("GET", $"/api/v1/audit/reports/user/{Alice}", Jwt(AdminUser, new[] { "USER", "OWNER" }));

        Assert.Equal(HttpStatusCode.OK, self.StatusCode);
        Assert.Equal(HttpStatusCode.OK, owner.StatusCode);
    }

    [Fact]
    public async Task ResourceHistory_NonAdminOnlySeesOwnEvents()
    {
        var response = await SendAsync("GET", "/api/v1/audit/resources/doc-1/history", Jwt(Mallory));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var history = await response.Content.ReadFromJsonAsync<ResourceHistory>();
        Assert.Equal(1, history!.TotalEvents);
        Assert.All(history.Events, e => Assert.Equal(Mallory, e.UserId));
    }

    [Fact]
    public async Task ResourceHistory_AdminSeesAllEvents()
    {
        var response = await SendAsync("GET", "/api/v1/audit/resources/doc-1/history", Jwt(AdminUser, new[] { "ADMIN" }));

        var history = await response.Content.ReadFromJsonAsync<ResourceHistory>();
        Assert.Equal(2, history!.TotalEvents);
    }

    [Theory]
    [InlineData("GET", "/api/v1/audit/reports/compliance")]
    [InlineData("GET", "/api/v1/audit/export")]
    [InlineData("POST", "/api/v1/audit/archive")]
    public async Task AdminOnlyRoutes_RejectNonAdmins(string method, string path)
    {
        var response = await SendAsync(method, path, Jwt(Mallory, new[] { "USER", "EDITOR" }));

        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
        Assert.Empty(_audit.Calls);
    }

    [Theory]
    [InlineData("GET", "/api/v1/audit/reports/compliance", "GetComplianceReport")]
    [InlineData("GET", "/api/v1/audit/export", "Export")]
    [InlineData("POST", "/api/v1/audit/archive", "ArchiveOldEvents")]
    public async Task AdminOnlyRoutes_AllowAdmins(string method, string path, string call)
    {
        var response = await SendAsync(method, path, Jwt(AdminUser, new[] { "ADMIN" }));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Contains(call, _audit.Calls);
    }

    [Fact]
    public async Task RecordEvent_ForAnotherUser_IsForbidden()
    {
        var response = await SendAsync("POST", "/api/v1/audit/events", Jwt(Mallory), Event(Alice));

        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
        Assert.Null(_audit.LastRecorded);
    }

    [Fact]
    public async Task RecordEvent_AdminCannotRecordForAnotherUserEither()
    {
        var response = await SendAsync("POST", "/api/v1/audit/events", Jwt(AdminUser, new[] { "ADMIN" }), Event(Alice));

        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
        Assert.Null(_audit.LastRecorded);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData(Alice)]
    public async Task RecordEvent_IsAttributedToTheCaller(string? bodyUserId)
    {
        var response = await SendAsync("POST", "/api/v1/audit/events", Jwt(Alice), Event(bodyUserId));

        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
        Assert.Equal(Alice, _audit.LastRecorded!.UserId);
    }

    private static async Task<(WebApplication App, HttpClient Client)> StartAsync(string? secret, IAuditService audit)
    {
        var builder = WebApplication.CreateBuilder(new WebApplicationOptions { EnvironmentName = "Testing" });

        // Drop appsettings.json / ASPNETCORE_URLS so the service's fixed :8090 endpoint is not bound.
        builder.Configuration.Sources.Clear();
        builder.Configuration.AddInMemoryCollection(new Dictionary<string, string?> { ["JWT_SECRET"] = secret });
        builder.WebHost.UseUrls("http://127.0.0.1:0");
        builder.Logging.ClearProviders();
        builder.Services.AddSingleton(audit);
        builder.Services.AddAuditAuthentication(builder.Configuration);

        var app = builder.Build();
        app.UseAuthentication();
        app.UseAuthorization();
        app.MapAuditEndpoints();
        await app.StartAsync();
        var address = app.Services.GetRequiredService<IServer>().Features.Get<IServerAddressesFeature>()!.Addresses.First();
        return (app, new HttpClient { BaseAddress = new Uri(address) });
    }

    private async Task<HttpResponseMessage> SendAsync(string method, string path, string? token, object? body = null)
    {
        var request = new HttpRequestMessage(new HttpMethod(method), path);
        if (token is not null)
        {
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
        }

        if (method == "POST")
        {
            request.Content = JsonContent.Create(body ?? Event(null));
        }

        return await _client.SendAsync(request);
    }

    private static object Event(string? userId) => new
    {
        userId,
        action = "share",
        resourceType = "document",
        resourceId = "doc-1",
    };

    private static Dictionary<string, object> Claims(string sub, string[] roles, string type, int expiresInSeconds)
    {
        var now = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
        return new Dictionary<string, object>
        {
            ["sub"] = sub,
            ["email"] = $"{sub}@example.test",
            ["roles"] = roles,
            ["type"] = type,
            ["iat"] = now - 10,
            ["exp"] = now + expiresInSeconds,
        };
    }

    private static string Jwt(
        string sub,
        string[]? roles = null,
        string type = "access",
        int expiresInSeconds = 300,
        string secret = Secret)
    {
        var header = B64(JsonSerializer.SerializeToUtf8Bytes(new { alg = "HS256", typ = "JWT" }));
        var payload = B64(JsonSerializer.SerializeToUtf8Bytes(Claims(sub, roles ?? new[] { "USER" }, type, expiresInSeconds)));
        using var hmac = new HMACSHA256(Encoding.UTF8.GetBytes(secret));
        var signature = B64(hmac.ComputeHash(Encoding.ASCII.GetBytes($"{header}.{payload}")));
        return $"{header}.{payload}.{signature}";
    }

    private static string B64(byte[] bytes) =>
        Convert.ToBase64String(bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_');

    private sealed class FakeAuditService : IAuditService
    {
        private readonly List<AuditEvent> _events = new();

        public List<string> Calls { get; } = new();

        public string? LastQueryUserId { get; private set; }

        public AuditEventRequest? LastRecorded { get; private set; }

        public void Seed(string id, string userId, string resourceId) => _events.Add(new AuditEvent
        {
            Id = id,
            UserId = userId,
            Action = "view",
            ResourceType = "document",
            ResourceId = resourceId,
            Timestamp = DateTime.UtcNow,
        });

        public Task<AuditEventResponse> RecordEventAsync(AuditEventRequest request)
        {
            Calls.Add("RecordEvent");
            LastRecorded = request;
            return Task.FromResult(new AuditEventResponse { Id = "evt-new", UserId = request.UserId });
        }

        public Task<AuditEventResponse?> GetEventAsync(string id)
        {
            Calls.Add("GetEvent");
            var match = _events.FirstOrDefault(e => e.Id == id);
            return Task.FromResult(match is null ? null : AuditEventResponse.FromEntity(match));
        }

        public Task<AuditEventPage> QueryEventsAsync(string? userId, string? action, string? resourceType, string? resourceId, DateTime? from, DateTime? to, int page, int pageSize)
        {
            Calls.Add("QueryEvents");
            LastQueryUserId = userId;
            var events = _events.Where(e => userId is null || e.UserId == userId).ToList();
            return Task.FromResult(new AuditEventPage { Events = events, Total = events.Count, Page = page, PageSize = pageSize });
        }

        public Task<UserActivityReport> GetUserActivityReportAsync(string userId, string period)
        {
            Calls.Add("GetUserActivityReport");
            return Task.FromResult(new UserActivityReport());
        }

        public Task<ResourceHistory> GetResourceHistoryAsync(string resourceId)
        {
            Calls.Add("GetResourceHistory");
            var events = _events.Where(e => e.ResourceId == resourceId).Select(AuditEventResponse.FromEntity).ToList();
            return Task.FromResult(new ResourceHistory { ResourceId = resourceId, TotalEvents = events.Count, Events = events });
        }

        public Task<ComplianceReport> GetComplianceReportAsync(string period)
        {
            Calls.Add("GetComplianceReport");
            return Task.FromResult(new ComplianceReport());
        }

        public Task<ExportResult> ExportAsync(DateTime from, DateTime to, string format)
        {
            Calls.Add("Export");
            return Task.FromResult(new ExportResult());
        }

        public Task<ArchiveResult> ArchiveOldEventsAsync()
        {
            Calls.Add("ArchiveOldEvents");
            return Task.FromResult(new ArchiveResult());
        }
    }
}
