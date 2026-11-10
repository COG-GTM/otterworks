using OtterWorks.AuditService.Models;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

public class AuditContractTests
{
    private static AuditEventRequest Valid() => new()
    {
        UserId = "user-1",
        Action = "auth.login.success",
        ResourceType = "user",
        ResourceId = "user-1",
        Outcome = "success",
        ServiceName = "auth-service",
    };

    [Theory]
    [InlineData("auth.login.success")]
    [InlineData("auth.token.refresh_denied")]
    [InlineData("permission.change")]
    [InlineData("share.create")]
    [InlineData("export")]
    [InlineData("delete")]
    public void IsValidAction_AcceptsContractActions(string action)
    {
        Assert.True(AuditContract.IsValidAction(action));
    }

    [Theory]
    [InlineData("create")]
    [InlineData("share")]
    [InlineData("Auth.Login")]
    [InlineData("auth.")]
    [InlineData("auth.login-success")]
    [InlineData("auth.1")]
    [InlineData("")]
    public void IsValidAction_RejectsUnknownActions(string action)
    {
        Assert.False(AuditContract.IsValidAction(action));
    }

    [Fact]
    public void Validate_ValidRequest_HasNoErrors()
    {
        Assert.Empty(AuditContract.Validate(Valid()));
    }

    [Theory]
    [InlineData("userId")]
    [InlineData("action")]
    [InlineData("resourceType")]
    [InlineData("outcome")]
    [InlineData("serviceName")]
    public void Validate_MissingRequiredField_ReportsIt(string field)
    {
        var request = Valid();
        switch (field)
        {
            case "userId": request.UserId = ""; break;
            case "action": request.Action = ""; break;
            case "resourceType": request.ResourceType = ""; break;
            case "outcome": request.Outcome = null; break;
            case "serviceName": request.ServiceName = null; break;
        }

        var errors = AuditContract.Validate(request);

        Assert.Contains(errors, e => e.StartsWith(field));
    }

    [Fact]
    public void Validate_RejectsUnknownOutcomeAndActorType()
    {
        var request = Valid();
        request.Outcome = "ok";
        request.ActorType = "robot";

        var errors = AuditContract.Validate(request);

        Assert.Contains(errors, e => e.StartsWith("outcome"));
        Assert.Contains(errors, e => e.StartsWith("actorType"));
    }

    [Fact]
    public void ToEntity_MapsSourceIpAliasAndV2Fields()
    {
        var request = Valid();
        request.SourceIp = "203.0.113.7";
        request.ActorEmail = "a@example.com";
        request.ActorType = "user";
        request.TenantId = "tenant-1";
        request.RequestId = "req-1";
        request.Timestamp = new DateTime(2026, 11, 10, 16, 0, 0, DateTimeKind.Utc);

        var entity = AuditContract.ToEntity(request);

        Assert.Equal("203.0.113.7", entity.IpAddress);
        Assert.Equal("a@example.com", entity.ActorEmail);
        Assert.Equal("user", entity.ActorType);
        Assert.Equal("tenant-1", entity.TenantId);
        Assert.Equal("req-1", entity.RequestId);
        Assert.Equal("success", entity.Outcome);
        Assert.Equal("auth-service", entity.ServiceName);
        Assert.Equal(request.Timestamp, entity.Timestamp);
    }

    [Fact]
    public void ToEntity_IpAddressWinsOverSourceIp()
    {
        var request = Valid();
        request.IpAddress = "198.51.100.1";
        request.SourceIp = "203.0.113.7";

        Assert.Equal("198.51.100.1", AuditContract.ToEntity(request).IpAddress);
    }

    [Fact]
    public void RedactDetails_ReplacesSecretLookingValues()
    {
        var details = new Dictionary<string, string>
        {
            ["password"] = "hunter2",
            ["refreshToken"] = "eyJ...",
            ["shareToken"] = "abc",
            ["Authorization"] = "Bearer x",
            ["api_key"] = "k",
            ["fileName"] = "report.pdf",
        };

        var redacted = AuditContract.RedactDetails(details)!;

        Assert.All(new[] { "password", "refreshToken", "shareToken", "Authorization", "api_key" },
            key => Assert.Equal(AuditContract.RedactedValue, redacted[key]));
        Assert.Equal("report.pdf", redacted["fileName"]);
    }
}
