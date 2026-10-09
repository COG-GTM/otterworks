using System.Net;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.IdentityModel.JsonWebTokens;
using Microsoft.IdentityModel.Tokens;
using Moq;
using OtterWorks.AuditService.Auth;
using OtterWorks.AuditService.Controllers;
using OtterWorks.AuditService.Models;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

public sealed class AuditEndpointAuthorizationTests : IAsyncLifetime
{
    private const string Secret = "audit-service-test-jwt-secret-that-is-long-enough-for-hs512-signing";
    private const string CallerId = "user-caller";
    private const string OtherUserId = "user-other";

    private readonly Mock<IAuditService> _auditService = new();
    private WebApplication _app = null!;
    private HttpClient _client = null!;

    public async Task InitializeAsync()
    {
        var builder = WebApplication.CreateBuilder();
        builder.WebHost.UseTestServer();
        builder.Configuration.AddInMemoryCollection(new Dictionary<string, string?> { ["JWT_SECRET"] = Secret });
        builder.Services.AddSingleton(_auditService.Object);
        builder.Services.AddAuditAuthorization(builder.Configuration);

        _app = builder.Build();
        _app.UseAuthentication();
        _app.UseAuthorization();
        _app.MapAuditEndpoints();
        await _app.StartAsync();
        _client = _app.GetTestClient();
    }

    public async Task DisposeAsync()
    {
        _client.Dispose();
        await _app.DisposeAsync();
    }

    [Theory]
    [InlineData("GET", "/api/v1/audit/events")]
    [InlineData("GET", "/api/v1/audit/events/e1")]
    [InlineData("GET", "/api/v1/audit/reports/user/user-other")]
    [InlineData("GET", "/api/v1/audit/resources/doc-1/history")]
    [InlineData("GET", "/api/v1/audit/reports/compliance")]
    [InlineData("GET", "/api/v1/audit/export")]
    [InlineData("POST", "/api/v1/audit/archive")]
    public async Task Request_WithoutToken_IsUnauthorized(string method, string path)
    {
        var response = await _client.SendAsync(new HttpRequestMessage(new HttpMethod(method), path));

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        _auditService.VerifyNoOtherCalls();
    }

    [Fact]
    public async Task Request_WithTokenSignedByWrongKey_IsUnauthorized()
    {
        var token = CreateToken(CallerId, ["ADMIN"], key: "a-completely-different-secret-that-is-also-long-enough-to-sign");

        var response = await SendAsync(HttpMethod.Get, "/api/v1/audit/events", token);

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task Request_WithExpiredToken_IsUnauthorized()
    {
        var token = CreateToken(CallerId, ["ADMIN"], expires: DateTime.UtcNow.AddMinutes(-5));

        var response = await SendAsync(HttpMethod.Get, "/api/v1/audit/events", token);

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task Request_WithRefreshToken_IsForbidden()
    {
        var token = CreateToken(CallerId, ["ADMIN"], tokenType: "refresh");

        var response = await SendAsync(HttpMethod.Get, "/api/v1/audit/events", token);

        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
        _auditService.VerifyNoOtherCalls();
    }

    [Fact]
    public async Task QueryEvents_AsRegularUser_IsScopedToCaller()
    {
        SetupQuery();

        var response = await SendAsync(HttpMethod.Get, "/api/v1/audit/events", UserToken());

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        _auditService.Verify(s => s.QueryEventsAsync(CallerId, null, null, null, null, null, 1, 20), Times.Once);
    }

    [Fact]
    public async Task QueryEvents_AsRegularUserForAnotherUser_IsForbidden()
    {
        var response = await SendAsync(HttpMethod.Get, $"/api/v1/audit/events?user_id={OtherUserId}", UserToken());

        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
        _auditService.VerifyNoOtherCalls();
    }

    [Fact]
    public async Task QueryEvents_AsAdmin_CanQueryAnyUser()
    {
        SetupQuery();

        var response = await SendAsync(HttpMethod.Get, $"/api/v1/audit/events?user_id={OtherUserId}", AdminToken());

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        _auditService.Verify(s => s.QueryEventsAsync(OtherUserId, null, null, null, null, null, 1, 20), Times.Once);
    }

    [Fact]
    public async Task QueryEvents_AsAdminWithoutFilter_IsNotScoped()
    {
        SetupQuery();

        var response = await SendAsync(HttpMethod.Get, "/api/v1/audit/events", AdminToken());

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        _auditService.Verify(s => s.QueryEventsAsync(null, null, null, null, null, null, 1, 20), Times.Once);
    }

    [Fact]
    public async Task GetEvent_OwnedByAnotherUser_IsNotFoundForRegularUser()
    {
        _auditService.Setup(s => s.GetEventAsync("e1"))
            .ReturnsAsync(new AuditEventResponse { Id = "e1", UserId = OtherUserId });

        var response = await SendAsync(HttpMethod.Get, "/api/v1/audit/events/e1", UserToken());

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }

    [Fact]
    public async Task GetEvent_OwnedByCaller_IsReturned()
    {
        _auditService.Setup(s => s.GetEventAsync("e1"))
            .ReturnsAsync(new AuditEventResponse { Id = "e1", UserId = CallerId });

        var response = await SendAsync(HttpMethod.Get, "/api/v1/audit/events/e1", UserToken());

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    [Fact]
    public async Task GetEvent_OwnedByAnotherUser_IsReturnedForAdmin()
    {
        _auditService.Setup(s => s.GetEventAsync("e1"))
            .ReturnsAsync(new AuditEventResponse { Id = "e1", UserId = OtherUserId });

        var response = await SendAsync(HttpMethod.Get, "/api/v1/audit/events/e1", AdminToken());

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    [Fact]
    public async Task UserActivityReport_ForAnotherUser_IsForbiddenForRegularUser()
    {
        var response = await SendAsync(HttpMethod.Get, $"/api/v1/audit/reports/user/{OtherUserId}", UserToken());

        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
        _auditService.VerifyNoOtherCalls();
    }

    [Fact]
    public async Task UserActivityReport_ForCaller_IsAllowed()
    {
        _auditService.Setup(s => s.GetUserActivityReportAsync(CallerId, "30d"))
            .ReturnsAsync(new UserActivityReport { UserId = CallerId });

        var response = await SendAsync(HttpMethod.Get, $"/api/v1/audit/reports/user/{CallerId}", UserToken());

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    [Fact]
    public async Task UserActivityReport_ForAnotherUser_IsAllowedForAdmin()
    {
        _auditService.Setup(s => s.GetUserActivityReportAsync(OtherUserId, "30d"))
            .ReturnsAsync(new UserActivityReport { UserId = OtherUserId });

        var response = await SendAsync(HttpMethod.Get, $"/api/v1/audit/reports/user/{OtherUserId}", AdminToken());

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }

    [Fact]
    public async Task ResourceHistory_AsRegularUser_IsScopedToCallerEvents()
    {
        _auditService.Setup(s => s.GetResourceHistoryAsync("doc-1", CallerId))
            .ReturnsAsync(new ResourceHistory { ResourceId = "doc-1" });

        var response = await SendAsync(HttpMethod.Get, "/api/v1/audit/resources/doc-1/history", UserToken());

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        _auditService.Verify(s => s.GetResourceHistoryAsync("doc-1", CallerId), Times.Once);
    }

    [Fact]
    public async Task ResourceHistory_AsAdmin_IsNotScoped()
    {
        _auditService.Setup(s => s.GetResourceHistoryAsync("doc-1", null))
            .ReturnsAsync(new ResourceHistory { ResourceId = "doc-1" });

        var response = await SendAsync(HttpMethod.Get, "/api/v1/audit/resources/doc-1/history", AdminToken());

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        _auditService.Verify(s => s.GetResourceHistoryAsync("doc-1", null), Times.Once);
    }

    [Theory]
    [InlineData("GET", "/api/v1/audit/reports/compliance")]
    [InlineData("GET", "/api/v1/audit/export")]
    [InlineData("POST", "/api/v1/audit/archive")]
    public async Task TenantWideOperations_AsRegularUser_AreForbidden(string method, string path)
    {
        var response = await SendAsync(new HttpMethod(method), path, UserToken());

        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
        _auditService.VerifyNoOtherCalls();
    }

    [Theory]
    [InlineData("ADMIN")]
    [InlineData("OWNER")]
    public async Task TenantWideOperations_AsAuditorRole_AreAllowed(string role)
    {
        _auditService.Setup(s => s.GetComplianceReportAsync("30d")).ReturnsAsync(new ComplianceReport());
        _auditService.Setup(s => s.ExportAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>(), "json")).ReturnsAsync(new ExportResult());
        _auditService.Setup(s => s.ArchiveOldEventsAsync()).ReturnsAsync(new ArchiveResult());
        var token = CreateToken(CallerId, [role]);

        Assert.Equal(HttpStatusCode.OK, (await SendAsync(HttpMethod.Get, "/api/v1/audit/reports/compliance", token)).StatusCode);
        Assert.Equal(HttpStatusCode.OK, (await SendAsync(HttpMethod.Get, "/api/v1/audit/export", token)).StatusCode);
        Assert.Equal(HttpStatusCode.OK, (await SendAsync(HttpMethod.Post, "/api/v1/audit/archive", token)).StatusCode);
    }

    [Fact]
    public async Task RecordEvent_ForAnotherUser_IsForbiddenForRegularUser()
    {
        var response = await SendAsync(HttpMethod.Post, "/api/v1/audit/events", UserToken(), NewEvent(OtherUserId));

        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
        _auditService.VerifyNoOtherCalls();
    }

    [Fact]
    public async Task RecordEvent_ForCaller_IsCreated()
    {
        _auditService.Setup(s => s.RecordEventAsync(It.IsAny<AuditEventRequest>()))
            .ReturnsAsync(new AuditEventResponse { Id = "e1", UserId = CallerId });

        var response = await SendAsync(HttpMethod.Post, "/api/v1/audit/events", UserToken(), NewEvent(CallerId));

        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
    }

    [Fact]
    public void AddAuditAuthorization_WithoutSecret_Throws()
    {
        var configuration = new ConfigurationBuilder().Build();

        Assert.Throws<InvalidOperationException>(() => new ServiceCollection().AddAuditAuthorization(configuration));
    }

    [Fact]
    public void AddAuditAuthorization_WithShortSecret_Throws()
    {
        var configuration = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?> { ["JWT_SECRET"] = "too-short" })
            .Build();

        Assert.Throws<InvalidOperationException>(() => new ServiceCollection().AddAuditAuthorization(configuration));
    }

    private void SetupQuery() =>
        _auditService
            .Setup(s => s.QueryEventsAsync(It.IsAny<string?>(), It.IsAny<string?>(), It.IsAny<string?>(), It.IsAny<string?>(),
                It.IsAny<DateTime?>(), It.IsAny<DateTime?>(), It.IsAny<int>(), It.IsAny<int>()))
            .ReturnsAsync(new AuditEventPage());

    private static AuditEventRequest NewEvent(string userId) => new()
    {
        UserId = userId,
        Action = "create",
        ResourceType = "document",
        ResourceId = "doc-1",
    };

    private static string UserToken() => CreateToken(CallerId, ["USER"]);

    private static string AdminToken() => CreateToken(CallerId, ["ADMIN"]);

    private static string CreateToken(
        string subject,
        string[] roles,
        string tokenType = "access",
        DateTime? expires = null,
        string key = Secret)
    {
        var expiry = expires ?? DateTime.UtcNow.AddMinutes(15);
        var descriptor = new SecurityTokenDescriptor
        {
            Claims = new Dictionary<string, object>
            {
                ["sub"] = subject,
                ["email"] = $"{subject}@example.test",
                ["roles"] = roles,
                ["type"] = tokenType,
            },
            NotBefore = expiry.AddMinutes(-30),
            IssuedAt = expiry.AddMinutes(-30),
            Expires = expiry,
            SigningCredentials = new SigningCredentials(
                new SymmetricSecurityKey(Encoding.UTF8.GetBytes(key)), SecurityAlgorithms.HmacSha384),
        };
        return new JsonWebTokenHandler().CreateToken(descriptor);
    }

    private Task<HttpResponseMessage> SendAsync(HttpMethod method, string path, string token, object? body = null)
    {
        var request = new HttpRequestMessage(method, path);
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
        if (body is not null)
            request.Content = JsonContent.Create(body);
        return _client.SendAsync(request);
    }
}
