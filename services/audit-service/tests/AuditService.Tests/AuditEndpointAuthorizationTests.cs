using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Security.Claims;
using System.Text;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using Microsoft.IdentityModel.JsonWebTokens;
using Microsoft.IdentityModel.Tokens;
using Moq;
using OtterWorks.AuditService.Models;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

public class AuditEndpointAuthorizationTests : IDisposable
{
    private const string Secret = "audit-service-test-jwt-secret-that-is-long-enough-for-hs512-signing!!";
    private const string Alice = "11111111-1111-1111-1111-111111111111";
    private const string Mallory = "22222222-2222-2222-2222-222222222222";
    private const string AdminId = "33333333-3333-3333-3333-333333333333";

    private readonly Mock<IAuditService> _auditService = new();
    private readonly WebApplicationFactory<Program> _factory;

    public AuditEndpointAuthorizationTests()
    {
        _factory = CreateFactory(Secret);
        _auditService
            .Setup(s => s.QueryEventsAsync(It.IsAny<string?>(), It.IsAny<string?>(), It.IsAny<string?>(), It.IsAny<string?>(),
                It.IsAny<DateTime?>(), It.IsAny<DateTime?>(), It.IsAny<int>(), It.IsAny<int>()))
            .ReturnsAsync(new AuditEventPage());
        _auditService
            .Setup(s => s.RecordEventAsync(It.IsAny<AuditEventRequest>()))
            .ReturnsAsync((AuditEventRequest r) => new AuditEventResponse { Id = "evt-1", UserId = r.UserId });
        _auditService
            .Setup(s => s.GetEventAsync("evt-alice"))
            .ReturnsAsync(new AuditEventResponse { Id = "evt-alice", UserId = Alice });
        _auditService
            .Setup(s => s.GetUserActivityReportAsync(It.IsAny<string>(), It.IsAny<string>()))
            .ReturnsAsync((string userId, string period) => new UserActivityReport { UserId = userId, Period = period });
        _auditService
            .Setup(s => s.GetResourceHistoryAsync(It.IsAny<string>(), It.IsAny<string?>()))
            .ReturnsAsync((string resourceId, string? _) => new ResourceHistory { ResourceId = resourceId });
        _auditService
            .Setup(s => s.GetComplianceReportAsync(It.IsAny<string>()))
            .ReturnsAsync(new ComplianceReport());
        _auditService
            .Setup(s => s.ExportAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>(), It.IsAny<string>()))
            .ReturnsAsync(new ExportResult());
        _auditService
            .Setup(s => s.ArchiveOldEventsAsync())
            .ReturnsAsync(new ArchiveResult());
    }

    public void Dispose() => _factory.Dispose();

    private WebApplicationFactory<Program> CreateFactory(string jwtSecret) =>
        new WebApplicationFactory<Program>().WithWebHostBuilder(builder =>
        {
            builder.UseSetting("JWT_SECRET", jwtSecret);
            builder.ConfigureServices(services =>
            {
                services.RemoveAll<IAuditService>();
                services.AddSingleton(_auditService.Object);
                var consumer = services.Single(d => d.ImplementationType == typeof(SnsConsumer));
                services.Remove(consumer);
            });
        });

    private static string Token(
        string userId,
        string[]? roles = null,
        string type = "access",
        string secret = Secret,
        string algorithm = SecurityAlgorithms.HmacSha384,
        DateTime? expires = null)
    {
        var identity = new ClaimsIdentity();
        identity.AddClaim(new Claim("sub", userId));
        identity.AddClaim(new Claim("type", type));
        foreach (var role in roles ?? new[] { "USER" })
        {
            identity.AddClaim(new Claim("roles", role));
        }

        var now = DateTime.UtcNow;
        var exp = expires ?? now.AddMinutes(10);
        return new JsonWebTokenHandler().CreateToken(new SecurityTokenDescriptor
        {
            Subject = identity,
            IssuedAt = exp.AddMinutes(-20),
            NotBefore = exp.AddMinutes(-20),
            Expires = exp,
            SigningCredentials = new SigningCredentials(
                new SymmetricSecurityKey(Encoding.UTF8.GetBytes(secret)), algorithm),
        });
    }

    private HttpClient Client(string? token, WebApplicationFactory<Program>? factory = null)
    {
        var client = (factory ?? _factory).CreateClient();
        if (token is not null)
        {
            client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", token);
        }
        return client;
    }

    public static IEnumerable<object[]> AllEndpoints() => new[]
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

    private static HttpRequestMessage Request(string method, string path)
    {
        var request = new HttpRequestMessage(new HttpMethod(method), path);
        if (method == "POST" && path.EndsWith("/events"))
        {
            request.Content = JsonContent.Create(new { userId = Alice, action = "delete", resourceType = "file", resourceId = "f-1" });
        }
        return request;
    }

    [Theory]
    [MemberData(nameof(AllEndpoints))]
    public async Task Endpoints_WithoutToken_Return401(string method, string path)
    {
        var response = await Client(null).SendAsync(Request(method, path));
        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Theory]
    [MemberData(nameof(AllEndpoints))]
    public async Task Endpoints_WithForgedSignature_Return401(string method, string path)
    {
        var forged = Token(AdminId, new[] { "ADMIN" }, secret: "attacker-chosen-secret-attacker-chosen-secret-attacker-chosen!!");
        var response = await Client(forged).SendAsync(Request(method, path));
        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task RefreshToken_IsRejected()
    {
        var response = await Client(Token(Alice, type: "refresh")).GetAsync("/api/v1/audit/events");
        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task ExpiredToken_IsRejected()
    {
        var response = await Client(Token(Alice, expires: DateTime.UtcNow.AddMinutes(-5))).GetAsync("/api/v1/audit/events");
        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task UnsignedToken_IsRejected()
    {
        var header = Base64UrlEncoder.Encode("{\"alg\":\"none\",\"typ\":\"JWT\"}");
        var exp = DateTimeOffset.UtcNow.AddMinutes(10).ToUnixTimeSeconds();
        var payload = Base64UrlEncoder.Encode($"{{\"sub\":\"{AdminId}\",\"roles\":[\"ADMIN\"],\"type\":\"access\",\"exp\":{exp}}}");
        var response = await Client($"{header}.{payload}.").GetAsync("/api/v1/audit/export");
        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task MissingJwtSecret_FailsClosed()
    {
        using var factory = CreateFactory(string.Empty);
        var response = await Client(Token(AdminId, new[] { "ADMIN" }), factory).GetAsync("/api/v1/audit/events");
        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Theory]
    [InlineData("GET", "/api/v1/audit/reports/compliance")]
    [InlineData("GET", "/api/v1/audit/export")]
    [InlineData("POST", "/api/v1/audit/archive")]
    public async Task AdminOnlyEndpoints_ForRegularUser_Return403(string method, string path)
    {
        var response = await Client(Token(Mallory)).SendAsync(Request(method, path));
        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
        _auditService.Verify(s => s.ExportAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>(), It.IsAny<string>()), Times.Never);
        _auditService.Verify(s => s.ArchiveOldEventsAsync(), Times.Never);
        _auditService.Verify(s => s.GetComplianceReportAsync(It.IsAny<string>()), Times.Never);
    }

    [Theory]
    [InlineData("ADMIN", "GET", "/api/v1/audit/reports/compliance")]
    [InlineData("OWNER", "GET", "/api/v1/audit/export")]
    [InlineData("admin", "POST", "/api/v1/audit/archive")]
    public async Task AdminOnlyEndpoints_ForAdmin_Return200(string role, string method, string path)
    {
        var token = Token(AdminId, new[] { "USER", role }, algorithm: SecurityAlgorithms.HmacSha512);
        var response = await Client(token).SendAsync(Request(method, path));
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    [Fact]
    public async Task RecordEvent_AttributesEventToCaller_NotRequestBody()
    {
        var client = Client(Token(Mallory));
        client.DefaultRequestHeaders.UserAgent.ParseAdd("MalloryAgent/1.0");
        var response = await client.PostAsJsonAsync("/api/v1/audit/events", new
        {
            userId = Alice,
            action = "delete",
            resourceType = "file",
            resourceId = "f-1",
            ipAddress = "10.9.9.9",
            userAgent = "Forged/1.0",
        });

        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
        _auditService.Verify(s => s.RecordEventAsync(It.Is<AuditEventRequest>(r =>
            r.UserId == Mallory && r.UserAgent == "MalloryAgent/1.0" && r.IpAddress != "10.9.9.9")), Times.Once);
    }

    [Fact]
    public async Task QueryEvents_ForAnotherUser_Returns403()
    {
        var response = await Client(Token(Mallory)).GetAsync($"/api/v1/audit/events?user_id={Alice}");
        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
        _auditService.Verify(s => s.QueryEventsAsync(It.IsAny<string?>(), It.IsAny<string?>(), It.IsAny<string?>(), It.IsAny<string?>(),
            It.IsAny<DateTime?>(), It.IsAny<DateTime?>(), It.IsAny<int>(), It.IsAny<int>()), Times.Never);
    }

    [Fact]
    public async Task QueryEvents_WithoutUserFilter_IsScopedToCaller()
    {
        var response = await Client(Token(Mallory)).GetAsync("/api/v1/audit/events");
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        _auditService.Verify(s => s.QueryEventsAsync(Mallory, It.IsAny<string?>(), It.IsAny<string?>(), It.IsAny<string?>(),
            It.IsAny<DateTime?>(), It.IsAny<DateTime?>(), It.IsAny<int>(), It.IsAny<int>()), Times.Once);
    }

    [Fact]
    public async Task QueryEvents_ForAdmin_IsNotScoped()
    {
        var response = await Client(Token(AdminId, new[] { "ADMIN" })).GetAsync("/api/v1/audit/events");
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        _auditService.Verify(s => s.QueryEventsAsync(null, It.IsAny<string?>(), It.IsAny<string?>(), It.IsAny<string?>(),
            It.IsAny<DateTime?>(), It.IsAny<DateTime?>(), It.IsAny<int>(), It.IsAny<int>()), Times.Once);
    }

    [Fact]
    public async Task GetEvent_OwnedByAnotherUser_Returns404()
    {
        var response = await Client(Token(Mallory)).GetAsync("/api/v1/audit/events/evt-alice");
        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }

    [Fact]
    public async Task GetEvent_ForOwnerAndAdmin_Returns200()
    {
        Assert.Equal(HttpStatusCode.OK, (await Client(Token(Alice)).GetAsync("/api/v1/audit/events/evt-alice")).StatusCode);
        Assert.Equal(HttpStatusCode.OK, (await Client(Token(AdminId, new[] { "ADMIN" })).GetAsync("/api/v1/audit/events/evt-alice")).StatusCode);
    }

    [Fact]
    public async Task UserActivityReport_ForAnotherUser_Returns403()
    {
        var response = await Client(Token(Mallory)).GetAsync($"/api/v1/audit/reports/user/{Alice}");
        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
        _auditService.Verify(s => s.GetUserActivityReportAsync(It.IsAny<string>(), It.IsAny<string>()), Times.Never);
    }

    [Fact]
    public async Task UserActivityReport_ForSelfAndAdmin_Returns200()
    {
        Assert.Equal(HttpStatusCode.OK, (await Client(Token(Alice)).GetAsync($"/api/v1/audit/reports/user/{Alice}")).StatusCode);
        Assert.Equal(HttpStatusCode.OK, (await Client(Token(AdminId, new[] { "ADMIN" })).GetAsync($"/api/v1/audit/reports/user/{Alice}")).StatusCode);
    }

    [Fact]
    public async Task ResourceHistory_ForRegularUser_IsScopedToCaller()
    {
        var response = await Client(Token(Mallory)).GetAsync("/api/v1/audit/resources/doc-1/history");
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        _auditService.Verify(s => s.GetResourceHistoryAsync("doc-1", Mallory), Times.Once);
    }

    [Fact]
    public async Task ResourceHistory_ForAdmin_IsNotScoped()
    {
        var response = await Client(Token(AdminId, new[] { "ADMIN" })).GetAsync("/api/v1/audit/resources/doc-1/history");
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        _auditService.Verify(s => s.GetResourceHistoryAsync("doc-1", null), Times.Once);
    }

    [Fact]
    public async Task Metrics_RemainsAnonymous()
    {
        var response = await Client(null).GetAsync("/metrics");
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }
}
