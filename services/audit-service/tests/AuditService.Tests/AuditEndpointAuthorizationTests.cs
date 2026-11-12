using System.Net;
using System.Net.Http.Json;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using Microsoft.Extensions.Hosting;
using Moq;
using OtterWorks.AuditService.Models;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

public class AuditEndpointAuthorizationTests : IClassFixture<WebApplicationFactory<Program>>
{
    private const string Alice = "alice-id";
    private const string Bob = "bob-id";

    private readonly WebApplicationFactory<Program> _factory;
    private readonly Mock<IAuditService> _auditService = new();

    public AuditEndpointAuthorizationTests(WebApplicationFactory<Program> factory)
    {
        _factory = factory.WithWebHostBuilder(builder =>
            builder.ConfigureTestServices(services =>
            {
                services.RemoveAll<IHostedService>();
                services.RemoveAll<IAuditService>();
                services.AddSingleton(_auditService.Object);
            }));

        _auditService
            .Setup(s => s.RecordEventAsync(It.IsAny<AuditEventRequest>()))
            .ReturnsAsync((AuditEventRequest r) => new AuditEventResponse
            {
                Id = "evt-1",
                UserId = r.UserId,
                Action = r.Action,
                ResourceType = r.ResourceType,
                ResourceId = r.ResourceId,
            });
        _auditService
            .Setup(s => s.QueryEventsAsync(It.IsAny<string?>(), It.IsAny<string?>(), It.IsAny<string?>(), It.IsAny<string?>(),
                It.IsAny<DateTime?>(), It.IsAny<DateTime?>(), It.IsAny<int>(), It.IsAny<int>()))
            .ReturnsAsync(new AuditEventPage());
        _auditService
            .Setup(s => s.GetUserActivityReportAsync(It.IsAny<string>(), It.IsAny<string>()))
            .ReturnsAsync((string userId, string period) => new UserActivityReport { UserId = userId, Period = period });
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

    private HttpClient ClientFor(string? userId, string? roles = null)
    {
        var client = _factory.CreateClient();
        if (userId is not null)
            client.DefaultRequestHeaders.Add("X-User-ID", userId);
        if (roles is not null)
            client.DefaultRequestHeaders.Add("X-User-Roles", roles);
        return client;
    }

    private static object EventBody(string? userId = null) => new
    {
        userId,
        action = "create",
        resourceType = "document",
        resourceId = "doc-1",
    };

    [Theory]
    [InlineData("GET", "/api/v1/audit/events")]
    [InlineData("GET", "/api/v1/audit/events/evt-1")]
    [InlineData("GET", "/api/v1/audit/reports/user/bob-id")]
    [InlineData("GET", "/api/v1/audit/resources/doc-1/history")]
    [InlineData("GET", "/api/v1/audit/reports/compliance")]
    [InlineData("GET", "/api/v1/audit/export")]
    [InlineData("POST", "/api/v1/audit/archive")]
    public async Task Requests_WithoutCallerIdentity_Return401(string method, string path)
    {
        var response = await ClientFor(null).SendAsync(new HttpRequestMessage(new HttpMethod(method), path));

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        _auditService.Verify(s => s.ArchiveOldEventsAsync(), Times.Never);
    }

    [Fact]
    public async Task RecordEvent_WithoutCallerIdentity_Returns401()
    {
        var response = await ClientFor(null).PostAsJsonAsync("/api/v1/audit/events", EventBody(Bob));

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        _auditService.Verify(s => s.RecordEventAsync(It.IsAny<AuditEventRequest>()), Times.Never);
    }

    [Theory]
    [InlineData("GET", "/api/v1/audit/reports/compliance")]
    [InlineData("GET", "/api/v1/audit/export")]
    [InlineData("POST", "/api/v1/audit/archive")]
    public async Task AdminEndpoints_ForRegularUser_Return403(string method, string path)
    {
        var response = await ClientFor(Alice, "USER").SendAsync(new HttpRequestMessage(new HttpMethod(method), path));

        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
        _auditService.Verify(s => s.ArchiveOldEventsAsync(), Times.Never);
        _auditService.Verify(s => s.ExportAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>(), It.IsAny<string>()), Times.Never);
        _auditService.Verify(s => s.GetComplianceReportAsync(It.IsAny<string>()), Times.Never);
    }

    [Theory]
    [InlineData("ADMIN")]
    [InlineData("USER,OWNER")]
    [InlineData("super_admin")]
    public async Task AdminEndpoints_ForAdmin_Succeed(string roles)
    {
        var client = ClientFor(Alice, roles);

        Assert.Equal(HttpStatusCode.OK, (await client.GetAsync("/api/v1/audit/reports/compliance")).StatusCode);
        Assert.Equal(HttpStatusCode.OK, (await client.GetAsync("/api/v1/audit/export")).StatusCode);
        Assert.Equal(HttpStatusCode.OK, (await client.PostAsync("/api/v1/audit/archive", null)).StatusCode);
        _auditService.Verify(s => s.ArchiveOldEventsAsync(), Times.Once);
    }

    [Fact]
    public async Task RecordEvent_InAnotherUsersName_Returns403()
    {
        var response = await ClientFor(Alice, "USER").PostAsJsonAsync("/api/v1/audit/events", EventBody(Bob));

        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
        _auditService.Verify(s => s.RecordEventAsync(It.IsAny<AuditEventRequest>()), Times.Never);
    }

    [Theory]
    [InlineData(null)]
    [InlineData(Alice)]
    public async Task RecordEvent_UsesCallerAsActor(string? bodyUserId)
    {
        var response = await ClientFor(Alice, "USER").PostAsJsonAsync("/api/v1/audit/events", EventBody(bodyUserId));

        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
        _auditService.Verify(s => s.RecordEventAsync(It.Is<AuditEventRequest>(r => r.UserId == Alice)), Times.Once);
    }

    [Fact]
    public async Task QueryEvents_ForAnotherUser_Returns403()
    {
        var response = await ClientFor(Alice, "USER").GetAsync($"/api/v1/audit/events?user_id={Bob}");

        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
    }

    [Fact]
    public async Task QueryEvents_WithoutFilter_IsScopedToCaller()
    {
        var response = await ClientFor(Alice, "USER").GetAsync("/api/v1/audit/events?resource=doc-1");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        _auditService.Verify(s => s.QueryEventsAsync(Alice, null, null, "doc-1", null, null, 1, 20), Times.Once);
    }

    [Fact]
    public async Task QueryEvents_ForAdmin_IsUnscoped()
    {
        var response = await ClientFor(Alice, "ADMIN").GetAsync("/api/v1/audit/events");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        _auditService.Verify(s => s.QueryEventsAsync(null, null, null, null, null, null, 1, 20), Times.Once);
    }

    [Fact]
    public async Task GetEvent_OwnedByAnotherUser_Returns404()
    {
        _auditService.Setup(s => s.GetEventAsync("evt-bob")).ReturnsAsync(new AuditEventResponse { Id = "evt-bob", UserId = Bob });
        _auditService.Setup(s => s.GetEventAsync("evt-alice")).ReturnsAsync(new AuditEventResponse { Id = "evt-alice", UserId = Alice });
        var client = ClientFor(Alice, "USER");

        Assert.Equal(HttpStatusCode.NotFound, (await client.GetAsync("/api/v1/audit/events/evt-bob")).StatusCode);
        Assert.Equal(HttpStatusCode.OK, (await client.GetAsync("/api/v1/audit/events/evt-alice")).StatusCode);
        Assert.Equal(HttpStatusCode.OK, (await ClientFor(Alice, "ADMIN").GetAsync("/api/v1/audit/events/evt-bob")).StatusCode);
    }

    [Fact]
    public async Task UserActivityReport_ForAnotherUser_Returns403()
    {
        var client = ClientFor(Alice, "USER");

        Assert.Equal(HttpStatusCode.Forbidden, (await client.GetAsync($"/api/v1/audit/reports/user/{Bob}")).StatusCode);
        Assert.Equal(HttpStatusCode.OK, (await client.GetAsync($"/api/v1/audit/reports/user/{Alice}")).StatusCode);
        Assert.Equal(HttpStatusCode.OK, (await ClientFor(Alice, "ADMIN").GetAsync($"/api/v1/audit/reports/user/{Bob}")).StatusCode);
        _auditService.Verify(s => s.GetUserActivityReportAsync(Bob, It.IsAny<string>()), Times.Once);
    }

    [Fact]
    public async Task ResourceHistory_ForRegularUser_OnlyContainsOwnEvents()
    {
        _auditService
            .Setup(s => s.GetResourceHistoryAsync("doc-1"))
            .ReturnsAsync(() => new ResourceHistory
            {
                ResourceId = "doc-1",
                TotalEvents = 2,
                Events = new List<AuditEventResponse>
                {
                    new() { Id = "evt-alice", UserId = Alice },
                    new() { Id = "evt-bob", UserId = Bob },
                },
            });

        var userHistory = await ClientFor(Alice, "USER").GetFromJsonAsync<ResourceHistory>("/api/v1/audit/resources/doc-1/history");
        var adminHistory = await ClientFor(Alice, "ADMIN").GetFromJsonAsync<ResourceHistory>("/api/v1/audit/resources/doc-1/history");

        Assert.NotNull(userHistory);
        Assert.Equal(1, userHistory.TotalEvents);
        Assert.Equal("evt-alice", Assert.Single(userHistory.Events).Id);
        Assert.NotNull(adminHistory);
        Assert.Equal(2, adminHistory.TotalEvents);
    }
}
