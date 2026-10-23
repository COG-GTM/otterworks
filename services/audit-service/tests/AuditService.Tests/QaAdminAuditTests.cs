using Amazon.DynamoDBv2;
using Amazon.DynamoDBv2.Model;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Moq;
using OtterWorks.AuditService.Config;
using OtterWorks.AuditService.Models;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

// QA admin-audit unit layer: write path, query filters, ordering and paging.
public class QaAdminAuditTests
{
    private readonly Mock<IAmazonDynamoDB> _dynamo = new();
    private readonly DynamoDbAuditRepository _repository;
    private readonly Mock<IAuditRepository> _mockRepository = new();
    private readonly OtterWorks.AuditService.Services.AuditService _service;

    public QaAdminAuditTests()
    {
        var options = Options.Create(new AwsSettings
        {
            DynamoDbTable = "qa-audit-events",
            Region = "us-east-1",
            S3ArchiveBucket = "qa-bucket",
            ArchiveAfterDays = 90,
        });
        _repository = new DynamoDbAuditRepository(_dynamo.Object, options, Mock.Of<ILogger<DynamoDbAuditRepository>>());
        _service = new OtterWorks.AuditService.Services.AuditService(
            _mockRepository.Object,
            Mock.Of<IAuditArchiver>(),
            options,
            Mock.Of<ILogger<OtterWorks.AuditService.Services.AuditService>>());
    }

    private static Dictionary<string, AttributeValue> Item(string id, string user, string action, DateTime ts) => new()
    {
        ["Id"] = new AttributeValue { S = id },
        ["UserId"] = new AttributeValue { S = user },
        ["Action"] = new AttributeValue { S = action },
        ["ResourceType"] = new AttributeValue { S = "AdminUser" },
        ["ResourceId"] = new AttributeValue { S = "res-" + id },
        ["Timestamp"] = new AttributeValue { S = ts.ToString("O") },
    };

    [Fact]
    public async Task RecordEventAsync_AssignsUniqueIdsAndUtcTimestamps()
    {
        var saved = new List<AuditEvent>();
        _mockRepository.Setup(r => r.SaveEventAsync(Capture.In(saved))).Returns(Task.CompletedTask);
        var request = new AuditEventRequest { UserId = "u1", Action = "user.suspended", ResourceType = "AdminUser", ResourceId = "r1" };

        var before = DateTime.UtcNow;
        var a = await _service.RecordEventAsync(request);
        var b = await _service.RecordEventAsync(request);

        Assert.NotEqual(a.Id, b.Id);
        Assert.True(Guid.TryParse(a.Id, out _));
        Assert.All(saved, e => Assert.Equal(DateTimeKind.Utc, e.Timestamp.Kind));
        Assert.All(saved, e => Assert.InRange(e.Timestamp, before.AddSeconds(-1), DateTime.UtcNow.AddSeconds(1)));
    }

    [Fact]
    public async Task RecordEventAsync_PreservesActorAndDetails()
    {
        AuditEvent? saved = null;
        _mockRepository.Setup(r => r.SaveEventAsync(It.IsAny<AuditEvent>()))
            .Callback<AuditEvent>(e => saved = e).Returns(Task.CompletedTask);
        var request = new AuditEventRequest
        {
            UserId = "actor-42", Action = "file.upload", ResourceType = "file", ResourceId = "f-1",
            Details = new Dictionary<string, string> { ["name"] = "report.pdf" },
            IpAddress = "10.1.2.3", UserAgent = "qa",
        };

        var resp = await _service.RecordEventAsync(request);

        Assert.Equal("actor-42", resp.UserId);
        Assert.NotNull(saved);
        Assert.Equal("report.pdf", saved!.Details!["name"]);
        Assert.Equal("10.1.2.3", saved.IpAddress);
    }

    [Fact]
    public async Task RecordEventAsync_PropagatesRepositoryFailure()
    {
        _mockRepository.Setup(r => r.SaveEventAsync(It.IsAny<AuditEvent>()))
            .ThrowsAsync(new AmazonDynamoDBException("table missing"));
        var request = new AuditEventRequest { UserId = "u", Action = "a", ResourceType = "t", ResourceId = "r" };

        await Assert.ThrowsAsync<AmazonDynamoDBException>(() => _service.RecordEventAsync(request));
    }

    [Fact]
    public async Task GetEventAsync_ReturnsNullWhenMissing()
    {
        _mockRepository.Setup(r => r.GetEventAsync("nope")).ReturnsAsync((AuditEvent?)null);
        Assert.Null(await _service.GetEventAsync("nope"));
    }

    [Fact]
    public async Task QueryEventsAsync_CombinesAllFiltersWithAnd()
    {
        ScanRequest? captured = null;
        _dynamo.Setup(d => d.ScanAsync(It.IsAny<ScanRequest>(), default))
            .Callback<ScanRequest, CancellationToken>((r, _) => captured = r)
            .ReturnsAsync(new ScanResponse { Items = new() });
        var from = new DateTime(2026, 1, 1, 0, 0, 0, DateTimeKind.Utc);
        var to = from.AddDays(1);

        await _repository.QueryEventsAsync("u1", "user.updated", "AdminUser", "r1", from, to, 1, 20);

        Assert.NotNull(captured);
        Assert.Equal("qa-audit-events", captured!.TableName);
        Assert.Equal("#uid = :uid AND #act = :act AND ResourceType = :rt AND ResourceId = :rid AND #ts >= :fromTs AND #ts <= :toTs",
            captured.FilterExpression);
        Assert.Equal("u1", captured.ExpressionAttributeValues[":uid"].S);
        Assert.Equal(from.ToString("O"), captured.ExpressionAttributeValues[":fromTs"].S);
        Assert.Equal("Timestamp", captured.ExpressionAttributeNames["#ts"]);
    }

    [Fact]
    public async Task QueryEventsAsync_ToOnly_DeclaresTimestampAlias()
    {
        ScanRequest? captured = null;
        _dynamo.Setup(d => d.ScanAsync(It.IsAny<ScanRequest>(), default))
            .Callback<ScanRequest, CancellationToken>((r, _) => captured = r)
            .ReturnsAsync(new ScanResponse { Items = new() });

        await _repository.QueryEventsAsync(null, null, null, null, null, DateTime.UtcNow, 1, 20);

        Assert.Equal("#ts <= :toTs", captured!.FilterExpression);
        Assert.Equal("Timestamp", captured.ExpressionAttributeNames["#ts"]);
    }

    [Fact]
    public async Task QueryEventsAsync_NoFilters_ScansWithoutExpression()
    {
        ScanRequest? captured = null;
        _dynamo.Setup(d => d.ScanAsync(It.IsAny<ScanRequest>(), default))
            .Callback<ScanRequest, CancellationToken>((r, _) => captured = r)
            .ReturnsAsync(new ScanResponse { Items = new() });

        var page = await _repository.QueryEventsAsync(null, null, null, null, null, null, 1, 20);

        Assert.Null(captured!.FilterExpression);
        Assert.Empty(page.Events);
        Assert.Equal(0, page.Total);
    }

    [Fact]
    public async Task QueryEventsAsync_SortsNewestFirstAcrossScanPagesAndPaginates()
    {
        var t0 = new DateTime(2026, 5, 1, 12, 0, 0, DateTimeKind.Utc);
        _dynamo.SetupSequence(d => d.ScanAsync(It.IsAny<ScanRequest>(), default))
            .ReturnsAsync(new ScanResponse
            {
                Items = new() { Item("a", "u", "x", t0), Item("c", "u", "x", t0.AddMinutes(2)) },
                LastEvaluatedKey = new() { ["Id"] = new AttributeValue { S = "c" } },
            })
            .ReturnsAsync(new ScanResponse { Items = new() { Item("b", "u", "x", t0.AddMinutes(1)) } });

        var page = await _repository.QueryEventsAsync("u", null, null, null, null, null, 2, 2);

        Assert.Equal(3, page.Total);
        Assert.Equal(2, page.Page);
        Assert.Single(page.Events);
        Assert.Equal("a", page.Events[0].Id);
        _dynamo.Verify(d => d.ScanAsync(It.IsAny<ScanRequest>(), default), Times.Exactly(2));
    }

    [Fact]
    public async Task QueryEventsAsync_FirstPageHasNewestEvent()
    {
        var t0 = DateTime.UtcNow;
        _dynamo.Setup(d => d.ScanAsync(It.IsAny<ScanRequest>(), default))
            .ReturnsAsync(new ScanResponse { Items = new() { Item("old", "u", "x", t0.AddHours(-1)), Item("new", "u", "x", t0) } });

        var page = await _repository.QueryEventsAsync(null, null, null, null, null, null, 1, 1);

        Assert.Equal("new", page.Events.Single().Id);
        Assert.Equal(DateTimeKind.Utc, page.Events[0].Timestamp.Kind);
    }

    [Fact]
    public async Task QueryEventsAsync_ToleratesItemsWithMissingTimestamp()
    {
        var item = Item("legacy", "u", "x", DateTime.UtcNow);
        item.Remove("Timestamp");
        _dynamo.Setup(d => d.ScanAsync(It.IsAny<ScanRequest>(), default))
            .ReturnsAsync(new ScanResponse { Items = new() { item } });

        var page = await _repository.QueryEventsAsync(null, null, null, null, null, null, 1, 20);

        Assert.Equal(DateTime.MinValue, page.Events.Single().Timestamp);
    }

    [Fact]
    public async Task GetEventAsync_ReturnsNullWhenItemMissing()
    {
        _dynamo.Setup(d => d.GetItemAsync(It.IsAny<GetItemRequest>(), default))
            .ReturnsAsync(new GetItemResponse { Item = new() });

        Assert.Null(await _repository.GetEventAsync("missing"));
    }
}
