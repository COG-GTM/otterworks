using System.Collections.Concurrent;
using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Security.Claims;
using System.Text;
using System.Text.Json;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using Microsoft.Extensions.Hosting;
using Microsoft.IdentityModel.JsonWebTokens;
using Microsoft.IdentityModel.Tokens;
using Moq;
using OtterWorks.AuditService.Models;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

public sealed class InMemoryAuditRepository : IAuditRepository
{
    public ConcurrentQueue<AuditEvent> Saved { get; } = new();
    public AuditEventQuery? LastQuery { get; private set; }
    public Func<AuditEvent, Task>? OnSave { get; set; }

    public async Task SaveEventAsync(AuditEvent auditEvent)
    {
        if (OnSave is not null)
            await OnSave(auditEvent);
        Saved.Enqueue(auditEvent);
    }

    public Task<AuditEvent?> GetEventAsync(string id) => Task.FromResult(Saved.FirstOrDefault(e => e.Id == id));

    public Task<AuditEventPage> QueryEventsAsync(AuditEventQuery query)
    {
        LastQuery = query;
        var events = Saved.Where(e =>
            (query.Action is null || e.Action == query.Action) &&
            (query.Outcome is null || e.Outcome == query.Outcome) &&
            (query.ServiceName is null || e.ServiceName == query.ServiceName) &&
            (query.TenantId is null || e.TenantId == query.TenantId)).ToList();
        return Task.FromResult(new AuditEventPage { Events = events, Total = events.Count, Page = query.Page, PageSize = query.PageSize });
    }

    public Task<List<AuditEvent>> GetAllUserEventsAsync(string userId) =>
        Task.FromResult(Saved.Where(e => e.UserId == userId).ToList());

    public Task<List<AuditEvent>> GetResourceHistoryAsync(string resourceId) =>
        Task.FromResult(Saved.Where(e => e.ResourceId == resourceId).ToList());

    public Task<List<AuditEvent>> GetEventsByDateRangeAsync(DateTime from, DateTime to) =>
        Task.FromResult(Saved.ToList());

    public Task<int> DeleteEventsAsync(IEnumerable<string> eventIds) => Task.FromResult(eventIds.Count());
}

public sealed class AuditApiFactory : WebApplicationFactory<Program>
{
    public const string JwtSecret = "audit-service-test-secret-that-is-long-enough-for-hs256-and-hs384";
    public const string IngestToken = "file-service-token";

    public InMemoryAuditRepository Repository { get; } = new();
    public Mock<IAuditArchiver> Archiver { get; } = new();
    public string? IngestTokens { get; init; } = $"auth-service-token, {IngestToken}";
    public TimeSpan SelfAuditTimeout { get; init; } = TimeSpan.FromSeconds(2);

    public AuditApiFactory()
    {
        Archiver
            .Setup(a => a.ExportAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>(), It.IsAny<string>()))
            .ReturnsAsync((DateTime from, DateTime to, string format) => new ExportResult
            {
                Format = format,
                EventCount = 3,
                DownloadUrl = "https://otterworks-audit-archive.s3.amazonaws.com/exports/x.json?X-Amz-Signature=secret-sig",
                From = from,
                To = to,
            });
        Archiver
            .Setup(a => a.ArchiveOldEventsAsync(It.IsAny<DateTime>()))
            .ReturnsAsync((DateTime cutoff) => new ArchiveResult
            {
                ArchivedCount = 42,
                S3Location = "s3://otterworks-audit-archive/archive/2026-11-10.json",
                ArchivedBefore = cutoff,
            });
    }

    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        builder.UseEnvironment("Testing");
        builder.UseSetting("JWT_SECRET", JwtSecret);
        builder.UseSetting("AUDIT_INGEST_TOKENS", IngestTokens ?? string.Empty);
        builder.ConfigureTestServices(services =>
        {
            services.RemoveAll<IHostedService>();
            services.RemoveAll<IAuditRepository>();
            services.RemoveAll<IAuditArchiver>();
            services.AddSingleton<IAuditRepository>(Repository);
            services.AddSingleton(Archiver.Object);
            services.Configure<SelfAuditOptions>(o =>
            {
                o.Timeout = SelfAuditTimeout;
                o.MaxAttempts = 2;
            });
        });
    }

    public static string Jwt(string userId, string email, IEnumerable<string> roles, string type = "access", string secret = JwtSecret)
    {
        var claims = new Dictionary<string, object>
        {
            ["email"] = email,
            ["roles"] = roles.ToArray(),
            ["type"] = type,
        };
        return new JsonWebTokenHandler().CreateToken(new SecurityTokenDescriptor
        {
            Subject = new ClaimsIdentity(new[] { new Claim("sub", userId) }),
            Claims = claims,
            Expires = DateTime.UtcNow.AddMinutes(5),
            SigningCredentials = new SigningCredentials(
                new SymmetricSecurityKey(Encoding.UTF8.GetBytes(secret)), SecurityAlgorithms.HmacSha256),
        });
    }

    public static string AdminJwt() => Jwt("admin-1", "admin@example.com", new[] { "USER", "ADMIN" });

    public static string UserJwt() => Jwt("user-1", "user@example.com", new[] { "USER" });
}

public class AuditApiTests
{
    private static object ValidEvent(string action = "share.create") => new
    {
        userId = "user-1",
        actorEmail = "user@example.com",
        actorType = "user",
        tenantId = "tenant-1",
        action,
        resourceType = "file",
        resourceId = "file-1",
        outcome = "success",
        details = new Dictionary<string, string> { ["sharedWith"] = "user-2" },
        sourceIp = "203.0.113.7",
        userAgent = "curl/8",
        requestId = "req-123",
        serviceName = "file-service",
        timestamp = "2026-11-10T16:00:00Z",
    };

    private static HttpRequestMessage Post(object body, string? token)
    {
        var request = new HttpRequestMessage(HttpMethod.Post, "/api/v1/audit/events") { Content = JsonContent.Create(body) };
        if (token is not null)
            request.Headers.Add("X-Audit-Token", token);
        return request;
    }

    private static HttpRequestMessage Admin(HttpMethod method, string url, string? jwt = null)
    {
        var request = new HttpRequestMessage(method, url);
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", jwt ?? AuditApiFactory.AdminJwt());
        request.Headers.Add("X-Forwarded-For", "198.51.100.9, 10.0.0.1");
        request.Headers.Add("X-Request-ID", "req-admin-1");
        request.Headers.UserAgent.ParseAdd("admin-console/1.0");
        return request;
    }

    // ---- Ingest auth ----

    [Fact]
    public async Task Ingest_WithoutToken_Returns401()
    {
        using var factory = new AuditApiFactory();
        var response = await factory.CreateClient().SendAsync(Post(ValidEvent(), null));

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        Assert.Empty(factory.Repository.Saved);
    }

    [Fact]
    public async Task Ingest_WithInvalidToken_Returns401()
    {
        using var factory = new AuditApiFactory();
        var response = await factory.CreateClient().SendAsync(Post(ValidEvent(), "wrong-token"));

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        Assert.Empty(factory.Repository.Saved);
    }

    [Fact]
    public async Task Ingest_WithUserJwtButNoToken_Returns401()
    {
        using var factory = new AuditApiFactory();
        var request = Post(ValidEvent(), null);
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", AuditApiFactory.AdminJwt());

        var response = await factory.CreateClient().SendAsync(request);

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task Ingest_WithAllowListedToken_StoresV2Event()
    {
        using var factory = new AuditApiFactory();
        var response = await factory.CreateClient().SendAsync(Post(ValidEvent(), AuditApiFactory.IngestToken));

        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
        var body = await response.Content.ReadFromJsonAsync<JsonElement>();
        Assert.Equal("share.create", body.GetProperty("action").GetString());
        Assert.Equal("203.0.113.7", body.GetProperty("sourceIp").GetString());
        Assert.Equal("203.0.113.7", body.GetProperty("ipAddress").GetString());

        var stored = Assert.Single(factory.Repository.Saved);
        Assert.Equal("user-1", stored.UserId);
        Assert.Equal("user@example.com", stored.ActorEmail);
        Assert.Equal("user", stored.ActorType);
        Assert.Equal("tenant-1", stored.TenantId);
        Assert.Equal("success", stored.Outcome);
        Assert.Equal("file-service", stored.ServiceName);
        Assert.Equal("req-123", stored.RequestId);
        Assert.Equal("203.0.113.7", stored.IpAddress);
        Assert.Equal(new DateTime(2026, 11, 10, 16, 0, 0, DateTimeKind.Utc), stored.Timestamp);
    }

    [Fact]
    public async Task Ingest_WhenTokensUnset_AcceptsWrites()
    {
        using var factory = new AuditApiFactory { IngestTokens = null };
        var response = await factory.CreateClient().SendAsync(Post(ValidEvent(), null));

        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
        Assert.Single(factory.Repository.Saved);
    }

    // ---- Validation ----

    [Fact]
    public async Task Ingest_UnknownAction_Returns400()
    {
        using var factory = new AuditApiFactory();
        var response = await factory.CreateClient().SendAsync(Post(ValidEvent("create"), AuditApiFactory.IngestToken));

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Contains("action", await response.Content.ReadAsStringAsync());
        Assert.Empty(factory.Repository.Saved);
    }

    [Fact]
    public async Task Ingest_MissingActor_Returns400()
    {
        using var factory = new AuditApiFactory();
        var body = new { action = "auth.logout", resourceType = "user", outcome = "success", serviceName = "auth-service" };

        var response = await factory.CreateClient().SendAsync(Post(body, AuditApiFactory.IngestToken));

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        Assert.Contains("userId", await response.Content.ReadAsStringAsync());
        Assert.Empty(factory.Repository.Saved);
    }

    [Fact]
    public async Task Ingest_SecretLookingDetails_AreRedactedBeforeStorage()
    {
        using var factory = new AuditApiFactory();
        var body = new
        {
            userId = "user-1",
            action = "auth.login.failure",
            resourceType = "user",
            outcome = "failure",
            serviceName = "auth-service",
            details = new Dictionary<string, string> { ["password"] = "hunter2", ["reason"] = "bad_credentials" },
        };

        var response = await factory.CreateClient().SendAsync(Post(body, AuditApiFactory.IngestToken));

        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
        var stored = Assert.Single(factory.Repository.Saved);
        Assert.Equal("[REDACTED]", stored.Details!["password"]);
        Assert.Equal("bad_credentials", stored.Details["reason"]);
        Assert.DoesNotContain("hunter2", await response.Content.ReadAsStringAsync());
    }

    // ---- Read authorization ----

    [Theory]
    [InlineData("/api/v1/audit/events")]
    [InlineData("/api/v1/audit/events/some-id")]
    [InlineData("/api/v1/audit/reports/compliance")]
    [InlineData("/api/v1/audit/resources/file-1/history")]
    public async Task Reads_WithoutJwt_Return401(string url)
    {
        using var factory = new AuditApiFactory();
        var response = await factory.CreateClient().GetAsync(url);

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task Reads_WithNonAdminJwt_Return403()
    {
        using var factory = new AuditApiFactory();
        var response = await factory.CreateClient().SendAsync(Admin(HttpMethod.Get, "/api/v1/audit/events", AuditApiFactory.UserJwt()));

        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
    }

    [Fact]
    public async Task Reads_WithAdminRefreshToken_Return403()
    {
        using var factory = new AuditApiFactory();
        var refresh = AuditApiFactory.Jwt("admin-1", "admin@example.com", new[] { "ADMIN" }, type: "refresh");

        var response = await factory.CreateClient().SendAsync(Admin(HttpMethod.Get, "/api/v1/audit/events", refresh));

        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
    }

    [Fact]
    public async Task Reads_WithJwtSignedByOtherSecret_Return401()
    {
        using var factory = new AuditApiFactory();
        var forged = AuditApiFactory.Jwt("admin-1", "admin@example.com", new[] { "ADMIN" },
            secret: "some-other-secret-that-is-also-long-enough-for-hs256-signing");

        var response = await factory.CreateClient().SendAsync(Admin(HttpMethod.Get, "/api/v1/audit/events", forged));

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task Query_WithAdminJwt_AppliesV2Filters()
    {
        using var factory = new AuditApiFactory();
        var response = await factory.CreateClient().SendAsync(Admin(HttpMethod.Get,
            "/api/v1/audit/events?action=share.create&outcome=denied&serviceName=file-service&tenantId=tenant-1&page=2&size=5"));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var query = factory.Repository.LastQuery!;
        Assert.Equal("share.create", query.Action);
        Assert.Equal("denied", query.Outcome);
        Assert.Equal("file-service", query.ServiceName);
        Assert.Equal("tenant-1", query.TenantId);
        Assert.Equal(2, query.Page);
        Assert.Equal(5, query.PageSize);
    }

    [Fact]
    public async Task Query_ReturnsV2ResponseShapeWithSourceIp()
    {
        using var factory = new AuditApiFactory();
        await factory.Repository.SaveEventAsync(new AuditEvent
        {
            Id = "e-1", UserId = "user-1", Action = "auth.login.success", ResourceType = "user",
            Outcome = "success", ServiceName = "auth-service", IpAddress = "203.0.113.9", Timestamp = DateTime.UtcNow,
        });

        var response = await factory.CreateClient().SendAsync(Admin(HttpMethod.Get, "/api/v1/audit/events"));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var body = await response.Content.ReadFromJsonAsync<JsonElement>();
        Assert.Equal(1, body.GetProperty("total").GetInt32());
        var evt = body.GetProperty("events")[0];
        Assert.Equal("203.0.113.9", evt.GetProperty("sourceIp").GetString());
        Assert.Equal("203.0.113.9", evt.GetProperty("ipAddress").GetString());
        Assert.Equal("auth-service", evt.GetProperty("serviceName").GetString());
    }

    [Fact]
    public async Task Query_SupportsSnakeCaseFilters()
    {
        using var factory = new AuditApiFactory();
        var response = await factory.CreateClient().SendAsync(Admin(HttpMethod.Get,
            "/api/v1/audit/events?user_id=user-9&service_name=auth-service&tenant_id=t-2&resource=file-1"));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var query = factory.Repository.LastQuery!;
        Assert.Equal("user-9", query.UserId);
        Assert.Equal("auth-service", query.ServiceName);
        Assert.Equal("t-2", query.TenantId);
        Assert.Equal("file-1", query.ResourceId);
    }

    // ---- Self-auditing ----

    private static void AssertSelfAudit(AuditEvent evt, string action, string resourceType, string outcome)
    {
        Assert.Equal(action, evt.Action);
        Assert.Equal(resourceType, evt.ResourceType);
        Assert.Equal(outcome, evt.Outcome);
        Assert.Equal("audit-service", evt.ServiceName);
        Assert.Equal("198.51.100.9", evt.IpAddress);
        Assert.Equal("req-admin-1", evt.RequestId);
        Assert.Equal("admin-console/1.0", evt.UserAgent);
        Assert.True(AuditContract.IsValidAction(evt.Action));
    }

    [Fact]
    public async Task Export_EmitsExportSelfAuditEvent()
    {
        using var factory = new AuditApiFactory();
        var response = await factory.CreateClient().SendAsync(Admin(HttpMethod.Get, "/api/v1/audit/export?format=csv"));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var evt = Assert.Single(factory.Repository.Saved);
        AssertSelfAudit(evt, "export", "export_archive", "success");
        Assert.Equal("admin-1", evt.UserId);
        Assert.Equal("admin@example.com", evt.ActorEmail);
        Assert.Equal("admin", evt.ActorType);
        Assert.Equal("https://otterworks-audit-archive.s3.amazonaws.com/exports/x.json", evt.ResourceId);
        Assert.Equal("csv", evt.Details!["format"]);
        Assert.Equal("3", evt.Details["eventCount"]);
        Assert.DoesNotContain(evt.Details.Values.Append(evt.ResourceId), v => v.Contains("X-Amz-Signature"));
    }

    [Fact]
    public async Task Export_InvalidFormat_EmitsFailureSelfAuditEvent()
    {
        using var factory = new AuditApiFactory();
        var response = await factory.CreateClient().SendAsync(Admin(HttpMethod.Get, "/api/v1/audit/export?format=xml"));

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
        var evt = Assert.Single(factory.Repository.Saved);
        AssertSelfAudit(evt, "export", "export_archive", "failure");
        Assert.Equal("invalid_format", evt.Details!["reason"]);
    }

    [Fact]
    public async Task Export_ByNonAdmin_EmitsDeniedSelfAuditEvent()
    {
        using var factory = new AuditApiFactory();
        var response = await factory.CreateClient().SendAsync(Admin(HttpMethod.Get, "/api/v1/audit/export", AuditApiFactory.UserJwt()));

        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
        var evt = Assert.Single(factory.Repository.Saved);
        AssertSelfAudit(evt, "export", "export_archive", "denied");
        Assert.Equal("user-1", evt.UserId);
        Assert.Equal("user", evt.ActorType);
        Assert.Equal("not_admin", evt.Details!["reason"]);
        factory.Archiver.Verify(a => a.ExportAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>(), It.IsAny<string>()), Times.Never);
    }

    [Fact]
    public async Task Archive_Unauthenticated_EmitsAnonymousDeniedSelfAuditEvent()
    {
        using var factory = new AuditApiFactory();
        var request = new HttpRequestMessage(HttpMethod.Post, "/api/v1/audit/archive");
        request.Headers.Add("X-Real-IP", "192.0.2.44");

        var response = await factory.CreateClient().SendAsync(request);

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        var evt = Assert.Single(factory.Repository.Saved);
        Assert.Equal("delete", evt.Action);
        Assert.Equal("denied", evt.Outcome);
        Assert.Equal("anonymous", evt.UserId);
        Assert.Equal("anonymous", evt.ActorType);
        Assert.Equal("192.0.2.44", evt.IpAddress);
        Assert.Equal("unauthenticated", evt.Details!["reason"]);
    }

    [Fact]
    public async Task Archive_EmitsDeleteSelfAuditEvent()
    {
        using var factory = new AuditApiFactory();
        var response = await factory.CreateClient().SendAsync(Admin(HttpMethod.Post, "/api/v1/audit/archive"));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var evt = Assert.Single(factory.Repository.Saved);
        AssertSelfAudit(evt, "delete", "audit_log", "success");
        Assert.Equal("admin-1", evt.UserId);
        Assert.Equal("s3://otterworks-audit-archive/archive/2026-11-10.json", evt.ResourceId);
        Assert.Equal("42", evt.Details!["archivedCount"]);
    }

    [Fact]
    public async Task UserReport_EmitsReportReadSelfAuditEvent()
    {
        using var factory = new AuditApiFactory();
        var response = await factory.CreateClient().SendAsync(Admin(HttpMethod.Get, "/api/v1/audit/reports/user/user-42?period=7d"));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var evt = Assert.Single(factory.Repository.Saved);
        AssertSelfAudit(evt, "audit.report.read", "user", "success");
        Assert.Equal("user-42", evt.ResourceId);
        Assert.Equal("7d", evt.Details!["period"]);
    }

    [Fact]
    public async Task UserReport_ByNonAdmin_EmitsDeniedWithTargetUser()
    {
        using var factory = new AuditApiFactory();
        var response = await factory.CreateClient().SendAsync(Admin(HttpMethod.Get, "/api/v1/audit/reports/user/user-42", AuditApiFactory.UserJwt()));

        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
        var evt = Assert.Single(factory.Repository.Saved);
        Assert.Equal("audit.report.read", evt.Action);
        Assert.Equal("denied", evt.Outcome);
        Assert.Equal("user-42", evt.ResourceId);
    }

    [Fact]
    public async Task Export_StillSucceeds_WhenSelfAuditStoreFails()
    {
        using var factory = new AuditApiFactory();
        factory.Repository.OnSave = _ => throw new InvalidOperationException("DynamoDB unavailable");
        var before = SelfAuditor.EmitFailures.WithLabels("export").Value;

        var response = await factory.CreateClient().SendAsync(Admin(HttpMethod.Get, "/api/v1/audit/export"));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Empty(factory.Repository.Saved);
        Assert.True(SelfAuditor.EmitFailures.WithLabels("export").Value >= before + 1);
    }

    [Fact]
    public async Task Archive_StillSucceeds_WhenSelfAuditStoreTimesOut()
    {
        using var factory = new AuditApiFactory { SelfAuditTimeout = TimeSpan.FromMilliseconds(100) };
        factory.Repository.OnSave = _ => Task.Delay(TimeSpan.FromSeconds(30));
        var before = SelfAuditor.EmitFailures.WithLabels("delete").Value;
        var stopwatch = System.Diagnostics.Stopwatch.StartNew();

        var response = await factory.CreateClient().SendAsync(Admin(HttpMethod.Post, "/api/v1/audit/archive"));

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.True(stopwatch.Elapsed < TimeSpan.FromSeconds(5), $"took {stopwatch.Elapsed}");
        Assert.True(SelfAuditor.EmitFailures.WithLabels("delete").Value >= before + 1);
    }

    [Fact]
    public async Task SelfAuditEvents_NeverContainBearerToken()
    {
        using var factory = new AuditApiFactory();
        var jwt = AuditApiFactory.AdminJwt();

        await factory.CreateClient().SendAsync(Admin(HttpMethod.Get, "/api/v1/audit/export", jwt));
        await factory.CreateClient().SendAsync(Admin(HttpMethod.Post, "/api/v1/audit/archive", jwt));
        await factory.CreateClient().SendAsync(Admin(HttpMethod.Get, "/api/v1/audit/reports/user/u", jwt));

        Assert.Equal(3, factory.Repository.Saved.Count);
        var serialized = JsonSerializer.Serialize(factory.Repository.Saved);
        Assert.DoesNotContain(jwt, serialized);
        Assert.DoesNotContain("Bearer", serialized);
        Assert.DoesNotContain("X-Amz-Signature", serialized);
    }
}
