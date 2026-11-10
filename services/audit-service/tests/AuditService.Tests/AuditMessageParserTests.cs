using System.Text.Json;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

public class AuditMessageParserTests
{
    private const string V2Body = """
        {
          "userId": "user-1",
          "actorEmail": "owner@example.com",
          "actorType": "user",
          "tenantId": "tenant-1",
          "action": "share.revoke",
          "resourceType": "share_link",
          "resourceId": "share-9",
          "outcome": "success",
          "details": { "fileId": "file-1", "shareToken": "should-not-survive" },
          "sourceIp": "203.0.113.7",
          "userAgent": "curl/8",
          "requestId": "req-123",
          "serviceName": "file-service",
          "timestamp": "2026-11-10T16:00:00Z"
        }
        """;

    [Fact]
    public void Parse_V2Message_MapsAllFields()
    {
        var evt = AuditMessageParser.Parse(V2Body, "msg-1")!;

        Assert.Equal("msg-1", evt.Id);
        Assert.Equal("user-1", evt.UserId);
        Assert.Equal("owner@example.com", evt.ActorEmail);
        Assert.Equal("user", evt.ActorType);
        Assert.Equal("tenant-1", evt.TenantId);
        Assert.Equal("share.revoke", evt.Action);
        Assert.Equal("share_link", evt.ResourceType);
        Assert.Equal("share-9", evt.ResourceId);
        Assert.Equal("success", evt.Outcome);
        Assert.Equal("203.0.113.7", evt.IpAddress);
        Assert.Equal("curl/8", evt.UserAgent);
        Assert.Equal("req-123", evt.RequestId);
        Assert.Equal("file-service", evt.ServiceName);
        Assert.Equal(new DateTime(2026, 11, 10, 16, 0, 0, DateTimeKind.Utc), evt.Timestamp);
        Assert.Equal("file-1", evt.Details!["fileId"]);
        Assert.Equal("[REDACTED]", evt.Details!["shareToken"]);
    }

    [Fact]
    public void Parse_V2MessageInsideSnsEnvelope_Unwraps()
    {
        var envelope = JsonSerializer.Serialize(new { Type = "Notification", Message = V2Body });

        var evt = AuditMessageParser.Parse(envelope, "msg-2")!;

        Assert.Equal("share.revoke", evt.Action);
        Assert.Equal("file-service", evt.ServiceName);
    }

    [Fact]
    public void Parse_LegacyFileShared_MapsToShareCreate()
    {
        var legacy = """
            {"eventType":"file_shared","fileId":"file-1","ownerId":"owner-1","sharedWithUserId":"user-2","timestamp":"2026-11-10T16:00:00Z"}
            """;
        var envelope = JsonSerializer.Serialize(new { Message = legacy });

        var evt = AuditMessageParser.Parse(envelope, "msg-3")!;

        Assert.Equal("owner-1", evt.UserId);
        Assert.Equal("share.create", evt.Action);
        Assert.Equal("file", evt.ResourceType);
        Assert.Equal("file-1", evt.ResourceId);
        Assert.Equal("success", evt.Outcome);
        Assert.Equal("file-service", evt.ServiceName);
        Assert.Equal("user-2", evt.Details!["sharedWithUserId"]);
        Assert.Equal("file_shared", evt.Details!["legacyEventType"]);
    }

    [Fact]
    public void Parse_IpAddressFieldStillAccepted()
    {
        var evt = AuditMessageParser.Parse(
            """{"userId":"u","action":"auth.logout","resourceType":"user","outcome":"success","serviceName":"auth-service","ipAddress":"198.51.100.1"}""",
            "msg-4")!;

        Assert.Equal("198.51.100.1", evt.IpAddress);
    }
}
