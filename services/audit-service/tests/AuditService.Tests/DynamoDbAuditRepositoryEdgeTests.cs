using Amazon.DynamoDBv2;
using Amazon.DynamoDBv2.Model;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Moq;
using OtterWorks.AuditService.Config;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

public class DynamoDbAuditRepositoryEdgeTests
{
    private const string Table = "test-audit-events";
    private readonly Mock<IAmazonDynamoDB> _dynamo = new();
    private readonly DynamoDbAuditRepository _repository;

    public DynamoDbAuditRepositoryEdgeTests()
    {
        _repository = new DynamoDbAuditRepository(
            _dynamo.Object,
            Options.Create(new AwsSettings { DynamoDbTable = Table }),
            NullLogger<DynamoDbAuditRepository>.Instance);
    }

    private static Dictionary<string, AttributeValue> Item(string id, string ts) => new()
    {
        ["Id"] = new AttributeValue { S = id },
        ["UserId"] = new AttributeValue { S = "u1" },
        ["Action"] = new AttributeValue { S = "read" },
        ["ResourceType"] = new AttributeValue { S = "file" },
        ["ResourceId"] = new AttributeValue { S = "f1" },
        ["Timestamp"] = new AttributeValue { S = ts },
    };

    [Fact]
    public async Task QueryEvents_WithFromAndTo_AddsTimestampFilters()
    {
        ScanRequest? captured = null;
        _dynamo.Setup(d => d.ScanAsync(It.IsAny<ScanRequest>(), default))
            .Callback<ScanRequest, CancellationToken>((r, _) => captured = r)
            .ReturnsAsync(new ScanResponse { Items = new() });
        var from = new DateTime(2026, 1, 1, 0, 0, 0, DateTimeKind.Utc);
        var to = new DateTime(2026, 2, 1, 0, 0, 0, DateTimeKind.Utc);

        await _repository.QueryEventsAsync(null, null, null, null, from, to, 1, 20);

        Assert.Equal("#ts >= :fromTs AND #ts <= :toTs", captured!.FilterExpression);
        Assert.Equal("Timestamp", captured.ExpressionAttributeNames["#ts"]);
        Assert.Equal(from.ToString("O"), captured.ExpressionAttributeValues[":fromTs"].S);
        Assert.Equal(to.ToString("O"), captured.ExpressionAttributeValues[":toTs"].S);
    }

    [Fact]
    public async Task QueryEvents_WithOnlyTo_RegistersTimestampAlias()
    {
        ScanRequest? captured = null;
        _dynamo.Setup(d => d.ScanAsync(It.IsAny<ScanRequest>(), default))
            .Callback<ScanRequest, CancellationToken>((r, _) => captured = r)
            .ReturnsAsync(new ScanResponse { Items = new() });

        await _repository.QueryEventsAsync(null, null, null, null, null, DateTime.UtcNow, 1, 20);

        Assert.Equal("#ts <= :toTs", captured!.FilterExpression);
        Assert.Equal("Timestamp", captured.ExpressionAttributeNames["#ts"]);
        Assert.False(captured.ExpressionAttributeValues.ContainsKey(":fromTs"));
    }

    [Fact]
    public async Task QueryEvents_WithOnlyResourceFilters_OmitsAttributeNames()
    {
        ScanRequest? captured = null;
        _dynamo.Setup(d => d.ScanAsync(It.IsAny<ScanRequest>(), default))
            .Callback<ScanRequest, CancellationToken>((r, _) => captured = r)
            .ReturnsAsync(new ScanResponse { Items = new() });

        await _repository.QueryEventsAsync(null, null, "file", "f1", null, null, 1, 20);

        Assert.Equal("ResourceType = :rt AND ResourceId = :rid", captured!.FilterExpression);
        Assert.Empty(captured.ExpressionAttributeNames);
    }

    [Fact]
    public async Task QueryEvents_FollowsScanPaginationAndSortsNewestFirst()
    {
        var lastKey = new Dictionary<string, AttributeValue> { ["id"] = new AttributeValue { S = "e1" } };
        var requests = new List<Dictionary<string, AttributeValue>?>();
        var responses = new Queue<ScanResponse>(new[]
        {
            new ScanResponse { Items = new() { Item("e1", "2026-01-01T00:00:00.0000000Z") }, LastEvaluatedKey = lastKey },
            new ScanResponse { Items = new() { Item("e2", "2026-01-02T00:00:00.0000000Z") } },
        });
        _dynamo.Setup(d => d.ScanAsync(It.IsAny<ScanRequest>(), default))
            .Callback<ScanRequest, CancellationToken>((r, _) => requests.Add(r.ExclusiveStartKey is { Count: > 0 } k ? new(k) : null))
            .ReturnsAsync(() => responses.Dequeue());

        var page = await _repository.QueryEventsAsync(null, null, null, null, null, null, 1, 1);

        Assert.Equal(2, page.Total);
        Assert.Equal("e2", Assert.Single(page.Events).Id);
        Assert.Null(requests[0]);
        Assert.Equal("e1", requests[1]!["id"].S);
    }

    [Fact]
    public async Task GetAllUserEvents_And_ResourceHistory_And_DateRange_FollowPagination()
    {
        var lastKey = new Dictionary<string, AttributeValue> { ["id"] = new AttributeValue { S = "k" } };
        var calls = 0;
        _dynamo.Setup(d => d.ScanAsync(It.IsAny<ScanRequest>(), default))
            .ReturnsAsync(() => calls++ % 2 == 0
                ? new ScanResponse { Items = new() { Item($"a{calls}", "2026-01-01T00:00:00Z") }, LastEvaluatedKey = lastKey }
                : new ScanResponse { Items = new() { Item($"b{calls}", "2026-01-03T00:00:00Z") } });

        var user = await _repository.GetAllUserEventsAsync("u1");
        var history = await _repository.GetResourceHistoryAsync("f1");
        var range = await _repository.GetEventsByDateRangeAsync(DateTime.MinValue, DateTime.UtcNow);

        Assert.Equal(2, user.Count);
        Assert.Equal(2, history.Count);
        Assert.Equal(2, range.Count);
        Assert.StartsWith("b", user[0].Id);
        Assert.Equal(6, calls);
    }

    [Fact]
    public async Task GetEvent_MapsLowercaseIdAndMissingOptionalFields()
    {
        _dynamo.Setup(d => d.GetItemAsync(It.IsAny<GetItemRequest>(), default))
            .ReturnsAsync(new GetItemResponse
            {
                Item = new Dictionary<string, AttributeValue>
                {
                    ["id"] = new AttributeValue { S = "lower" },
                    ["Timestamp"] = new AttributeValue { S = "not-a-date" },
                },
            });

        var e = await _repository.GetEventAsync("lower");

        Assert.NotNull(e);
        Assert.Equal("lower", e!.Id);
        Assert.Equal(string.Empty, e.UserId);
        Assert.Equal(string.Empty, e.Action);
        Assert.Equal(string.Empty, e.ResourceType);
        Assert.Equal(string.Empty, e.ResourceId);
        Assert.Equal(DateTime.MinValue, e.Timestamp);
        Assert.Null(e.IpAddress);
        Assert.Null(e.UserAgent);
        Assert.Null(e.Details);
    }

    [Fact]
    public async Task GetEvent_MapsAllFieldsIncludingDetails()
    {
        var item = Item("full", "2026-05-06T07:08:09.0000000Z");
        item["IpAddress"] = new AttributeValue { S = "1.2.3.4" };
        item["UserAgent"] = new AttributeValue { S = "agent" };
        item["Details"] = new AttributeValue { M = new() { ["k"] = new AttributeValue { S = "v" } } };
        _dynamo.Setup(d => d.GetItemAsync(It.IsAny<GetItemRequest>(), default))
            .ReturnsAsync(new GetItemResponse { Item = item });

        var e = await _repository.GetEventAsync("full");

        Assert.Equal("full", e!.Id);
        Assert.Equal("1.2.3.4", e.IpAddress);
        Assert.Equal("agent", e.UserAgent);
        Assert.Equal("v", e.Details!["k"]);
        Assert.Equal(DateTimeKind.Utc, e.Timestamp.Kind);
        Assert.Equal(new DateTime(2026, 5, 6, 7, 8, 9, DateTimeKind.Utc), e.Timestamp);
    }

    [Fact]
    public async Task GetEvent_WithNoIdAttributes_UsesEmptyId()
    {
        _dynamo.Setup(d => d.GetItemAsync(It.IsAny<GetItemRequest>(), default))
            .ReturnsAsync(new GetItemResponse
            {
                Item = new Dictionary<string, AttributeValue> { ["UserId"] = new AttributeValue { S = "u" } },
            });

        var e = await _repository.GetEventAsync("x");

        Assert.Equal(string.Empty, e!.Id);
        Assert.Equal("u", e.UserId);
    }

    [Fact]
    public async Task GetEvent_WithNullItem_ReturnsNull()
    {
        _dynamo.Setup(d => d.GetItemAsync(It.IsAny<GetItemRequest>(), default))
            .ReturnsAsync(new GetItemResponse { Item = null });

        Assert.Null(await _repository.GetEventAsync("none"));
    }

    [Fact]
    public async Task SaveEvent_WithEmptyDetails_OmitsDetailsAttribute()
    {
        PutItemRequest? captured = null;
        _dynamo.Setup(d => d.PutItemAsync(It.IsAny<PutItemRequest>(), default))
            .Callback<PutItemRequest, CancellationToken>((r, _) => captured = r)
            .ReturnsAsync(new PutItemResponse());

        await _repository.SaveEventAsync(new AuditEvent { Id = "e", Details = new Dictionary<string, string>() });

        Assert.False(captured!.Item.ContainsKey("Details"));
        Assert.Equal("e", captured.Item["id"].S);
    }

    private static Dictionary<string, List<WriteRequest>> Unprocessed(params string[] ids) => new()
    {
        [Table] = ids.Select(id => new WriteRequest
        {
            DeleteRequest = new DeleteRequest { Key = new() { ["id"] = new AttributeValue { S = id } } },
        }).ToList(),
    };

    [Fact]
    public async Task DeleteEvents_RetriesUnprocessedItemsUntilDone()
    {
        var requests = new List<BatchWriteItemRequest>();
        var responses = new Queue<BatchWriteItemResponse>(new[]
        {
            new BatchWriteItemResponse { UnprocessedItems = Unprocessed("e2") },
            new BatchWriteItemResponse { UnprocessedItems = new() },
        });
        _dynamo.Setup(d => d.BatchWriteItemAsync(It.IsAny<BatchWriteItemRequest>(), default))
            .Callback<BatchWriteItemRequest, CancellationToken>((r, _) => requests.Add(r))
            .ReturnsAsync(() => responses.Dequeue());

        var deleted = await _repository.DeleteEventsAsync(new[] { "e1", "e2" });

        Assert.Equal(2, deleted);
        Assert.Equal(2, requests.Count);
        Assert.Equal("e2", Assert.Single(requests[1].RequestItems[Table]).DeleteRequest.Key["id"].S);
    }

    [Fact]
    public async Task DeleteEvents_ReportsItemsStillUnprocessedAfterFiveRetries()
    {
        var calls = 0;
        _dynamo.Setup(d => d.BatchWriteItemAsync(It.IsAny<BatchWriteItemRequest>(), default))
            .Callback(() => calls++)
            .ReturnsAsync(() => new BatchWriteItemResponse { UnprocessedItems = Unprocessed("e2", "e3") });

        var deleted = await _repository.DeleteEventsAsync(new[] { "e1", "e2", "e3" });

        Assert.Equal(1, deleted);
        Assert.Equal(6, calls);
    }

    [Fact]
    public async Task DeleteEvents_WithNoIds_MakesNoCalls()
    {
        var deleted = await _repository.DeleteEventsAsync(Array.Empty<string>());

        Assert.Equal(0, deleted);
        _dynamo.Verify(d => d.BatchWriteItemAsync(It.IsAny<BatchWriteItemRequest>(), default), Times.Never);
    }
}
