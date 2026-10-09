using OtterWorks.AuditService.Config;
using OtterWorks.AuditService.Models;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

public class AuditEventValidatorTests
{
    private static readonly AuditLimits Limits = new()
    {
        MaxFieldLength = 10,
        MaxIpAddressLength = 8,
        MaxUserAgentLength = 8,
        MaxDetailsEntries = 3,
        MaxDetailKeyLength = 5,
        MaxDetailValueLength = 6,
        MaxDetailsTotalLength = 20,
    };

    [Fact]
    public void Validate_ValidRequest_ReturnsNull()
    {
        var request = ValidRequest();
        request.Details = new Dictionary<string, string> { ["a"] = "123456", ["b"] = "x" };

        Assert.Null(AuditEventValidator.Validate(request, Limits));
    }

    [Fact]
    public void Validate_MissingRequiredField_ReturnsError()
    {
        var request = ValidRequest();
        request.ResourceId = " ";

        Assert.Equal("UserId, Action, ResourceType, and ResourceId are required.", AuditEventValidator.Validate(request, Limits));
    }

    [Theory]
    [InlineData("user")]
    [InlineData("ip")]
    [InlineData("agent")]
    public void Validate_OversizedField_ReturnsError(string field)
    {
        var request = ValidRequest();
        switch (field)
        {
            case "user": request.UserId = new string('u', 11); break;
            case "ip": request.IpAddress = new string('1', 9); break;
            case "agent": request.UserAgent = new string('a', 9); break;
        }

        Assert.NotNull(AuditEventValidator.Validate(request, Limits));
    }

    [Fact]
    public void Validate_TooManyDetails_ReturnsError()
    {
        var request = ValidRequest();
        request.Details = Enumerable.Range(1, 4).ToDictionary(i => $"k{i}", _ => "v");

        Assert.Contains("at most 3 entries", AuditEventValidator.Validate(request, Limits));
    }

    [Fact]
    public void Validate_OversizedDetailKeyOrValue_ReturnsError()
    {
        var longKey = ValidRequest();
        longKey.Details = new Dictionary<string, string> { ["toolong"] = "v" };
        var longValue = ValidRequest();
        longValue.Details = new Dictionary<string, string> { ["k"] = "1234567" };

        Assert.Contains("keys", AuditEventValidator.Validate(longKey, Limits));
        Assert.Contains("values", AuditEventValidator.Validate(longValue, Limits));
    }

    [Fact]
    public void Validate_DetailsTotalTooLarge_ReturnsError()
    {
        var request = ValidRequest();
        request.Details = new Dictionary<string, string> { ["aaaa"] = "123456", ["bbbb"] = "123456", ["c"] = "12" };

        Assert.Contains("in total", AuditEventValidator.Validate(request, Limits));
    }

    [Fact]
    public void Normalize_TruncatesFieldsAndDropsExcessDetails()
    {
        var auditEvent = new AuditEvent
        {
            UserId = new string('u', 20),
            Action = "create",
            ResourceType = "doc",
            ResourceId = "d1",
            UserAgent = new string('a', 20),
            Details = new Dictionary<string, string>
            {
                ["a"] = "1234567890",
                ["toolong"] = "x",
                ["b"] = "1",
                ["c"] = "1",
                ["d"] = "1",
            },
        };

        AuditEventValidator.Normalize(auditEvent, Limits);

        Assert.Equal(10, auditEvent.UserId.Length);
        Assert.Equal(8, auditEvent.UserAgent!.Length);
        Assert.Equal(3, auditEvent.Details!.Count);
        Assert.Equal("123456", auditEvent.Details["a"]);
        Assert.False(auditEvent.Details.ContainsKey("toolong"));
        Assert.False(auditEvent.Details.ContainsKey("d"));
    }

    private static AuditEventRequest ValidRequest() => new()
    {
        UserId = "user-1",
        Action = "create",
        ResourceType = "document",
        ResourceId = "doc-1",
        IpAddress = "10.0.0.1",
        UserAgent = "agent",
    };
}
