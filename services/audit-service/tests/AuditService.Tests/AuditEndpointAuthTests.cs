using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text;
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

public class AuditEndpointAuthTests : IClassFixture<AuditEndpointAuthTests.Factory>
{
    private const string JwtSecret = "test-jwt-secret-that-is-long-enough-for-hmac-sha-256";
    private const string ServiceToken = "test-audit-service-token";

    private readonly Factory _factory;

    public AuditEndpointAuthTests(Factory factory)
    {
        _factory = factory;
        _factory.AuditService.Reset();
        _factory.AuditService
            .Setup(s => s.QueryEventsAsync(It.IsAny<string?>(), It.IsAny<string?>(), It.IsAny<string?>(), It.IsAny<string?>(),
                It.IsAny<DateTime?>(), It.IsAny<DateTime?>(), It.IsAny<int>(), It.IsAny<int>()))
            .ReturnsAsync(new AuditEventPage());
        _factory.AuditService
            .Setup(s => s.RecordEventAsync(It.IsAny<AuditEventRequest>()))
            .ReturnsAsync((AuditEventRequest r) => new AuditEventResponse { Id = "evt-1", UserId = r.UserId });
        _factory.AuditService
            .Setup(s => s.ArchiveOldEventsAsync())
            .ReturnsAsync(new ArchiveResult());
    }

    [Theory]
    [InlineData("GET", "/api/v1/audit/events")]
    [InlineData("GET", "/api/v1/audit/events/evt-1")]
    [InlineData("GET", "/api/v1/audit/reports/user/alice")]
    [InlineData("GET", "/api/v1/audit/resources/r1/history")]
    [InlineData("GET", "/api/v1/audit/reports/compliance")]
    [InlineData("GET", "/api/v1/audit/export")]
    [InlineData("POST", "/api/v1/audit/archive")]
    [InlineData("POST", "/api/v1/audit/events")]
    public async Task AllRoutes_RejectAnonymousCallers(string method, string path)
    {
        var client = _factory.CreateClient();
        var request = new HttpRequestMessage(new HttpMethod(method), path);
        if (method == "POST")
            request.Content = JsonContent.Create(new { });

        var response = await client.SendAsync(request);

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task ForgedToken_IsRejected()
    {
        var client = ClientWithToken(Token("mallory", new[] { "ADMIN" }, secret: "some-other-secret-that-is-long-enough-123"));

        var response = await client.GetAsync("/api/v1/audit/events");

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task RefreshToken_IsRejected()
    {
        var client = ClientWithToken(Token("mallory", new[] { "ADMIN" }, type: "refresh"));

        var response = await client.GetAsync("/api/v1/audit/events");

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task WrongServiceToken_IsRejected()
    {
        var client = _factory.CreateClient();
        client.DefaultRequestHeaders.Add("X-Service-Token", "wrong");

        var response = await client.GetAsync("/api/v1/audit/events");

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task QueryEvents_NonAdmin_IsScopedToOwnUserId()
    {
        var client = ClientWithToken(Token("mallory", new[] { "USER" }));

        var response = await client.GetAsync("/api/v1/audit/events");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        _factory.AuditService.Verify(s => s.QueryEventsAsync("mallory", null, null, null, null, null, 1, 20), Times.Once);
    }

    [Fact]
    public async Task QueryEvents_NonAdmin_CannotQueryAnotherUser()
    {
        var client = ClientWithToken(Token("mallory", new[] { "USER" }));

        var response = await client.GetAsync("/api/v1/audit/events?user_id=alice");

        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
        _factory.AuditService.Verify(s => s.QueryEventsAsync(It.IsAny<string?>(), It.IsAny<string?>(), It.IsAny<string?>(),
            It.IsAny<string?>(), It.IsAny<DateTime?>(), It.IsAny<DateTime?>(), It.IsAny<int>(), It.IsAny<int>()), Times.Never);
    }

    [Fact]
    public async Task QueryEvents_Admin_CanQueryAllUsers()
    {
        var client = ClientWithToken(Token("root", new[] { "ADMIN" }));

        var response = await client.GetAsync("/api/v1/audit/events");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        _factory.AuditService.Verify(s => s.QueryEventsAsync(null, null, null, null, null, null, 1, 20), Times.Once);
    }

    [Fact]
    public async Task QueryEvents_ServiceToken_CanQueryAllUsers()
    {
        var client = _factory.CreateClient();
        client.DefaultRequestHeaders.Add("X-Service-Token", ServiceToken);

        var response = await client.GetAsync("/api/v1/audit/events");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    [Fact]
    public async Task GetEvent_NonAdmin_CannotReadAnotherUsersEvent()
    {
        _factory.AuditService.Setup(s => s.GetEventAsync("evt-1"))
            .ReturnsAsync(new AuditEventResponse { Id = "evt-1", UserId = "alice" });
        var client = ClientWithToken(Token("mallory", new[] { "USER" }));

        var response = await client.GetAsync("/api/v1/audit/events/evt-1");

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }

    [Fact]
    public async Task GetEvent_Owner_CanReadOwnEvent()
    {
        _factory.AuditService.Setup(s => s.GetEventAsync("evt-1"))
            .ReturnsAsync(new AuditEventResponse { Id = "evt-1", UserId = "alice" });
        var client = ClientWithToken(Token("alice", new[] { "USER" }));

        var response = await client.GetAsync("/api/v1/audit/events/evt-1");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    [Fact]
    public async Task UserActivityReport_NonAdmin_CannotReadAnotherUser()
    {
        var client = ClientWithToken(Token("mallory", new[] { "USER" }));

        var response = await client.GetAsync("/api/v1/audit/reports/user/alice");

        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
    }

    [Fact]
    public async Task RecordEvent_NonAdmin_CannotForgeAnotherUsersIdentity()
    {
        var client = ClientWithToken(Token("mallory", new[] { "USER" }));

        var response = await client.PostAsJsonAsync("/api/v1/audit/events", new AuditEventRequest
        {
            UserId = "alice",
            Action = "file.delete",
            ResourceType = "file",
            ResourceId = "f1",
        });

        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
        _factory.AuditService.Verify(s => s.RecordEventAsync(It.Is<AuditEventRequest>(r => r.UserId == "mallory")), Times.Once);
    }

    [Theory]
    [InlineData("GET", "/api/v1/audit/resources/r1/history")]
    [InlineData("GET", "/api/v1/audit/reports/compliance")]
    [InlineData("GET", "/api/v1/audit/export")]
    [InlineData("POST", "/api/v1/audit/archive")]
    public async Task AdminRoutes_RejectNonAdmin(string method, string path)
    {
        var client = ClientWithToken(Token("mallory", new[] { "USER", "EDITOR" }));

        var response = await client.SendAsync(new HttpRequestMessage(new HttpMethod(method), path));

        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
        _factory.AuditService.Verify(s => s.ArchiveOldEventsAsync(), Times.Never);
    }

    [Fact]
    public async Task Archive_Admin_IsAllowed()
    {
        var client = ClientWithToken(Token("root", new[] { "OWNER" }));

        var response = await client.PostAsync("/api/v1/audit/archive", null);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        _factory.AuditService.Verify(s => s.ArchiveOldEventsAsync(), Times.Once);
    }

    private HttpClient ClientWithToken(string token)
    {
        var client = _factory.CreateClient();
        client.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", token);
        return client;
    }

    private static string Token(string subject, string[] roles, string type = "access", string secret = JwtSecret)
    {
        var descriptor = new SecurityTokenDescriptor
        {
            Claims = new Dictionary<string, object>
            {
                ["sub"] = subject,
                ["roles"] = roles,
                ["type"] = type,
            },
            Expires = DateTime.UtcNow.AddMinutes(5),
            SigningCredentials = new SigningCredentials(
                new SymmetricSecurityKey(Encoding.UTF8.GetBytes(secret)), SecurityAlgorithms.HmacSha256),
        };
        return new JsonWebTokenHandler().CreateToken(descriptor);
    }

    public sealed class Factory : WebApplicationFactory<Program>
    {
        public Mock<IAuditService> AuditService { get; } = new();

        protected override void ConfigureWebHost(IWebHostBuilder builder)
        {
            builder.UseSetting("JWT_SECRET", JwtSecret);
            builder.UseSetting("AUDIT_SERVICE_TOKEN", ServiceToken);
            builder.ConfigureTestServices(services =>
            {
                services.RemoveAll<IHostedService>();
                services.RemoveAll<IAuditService>();
                services.AddSingleton(AuditService.Object);
            });
        }
    }
}
