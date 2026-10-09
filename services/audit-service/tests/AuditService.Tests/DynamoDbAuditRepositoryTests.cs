using Amazon.DynamoDBv2;
using Amazon.DynamoDBv2.Model;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Moq;
using OtterWorks.AuditService.Config;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

public class DynamoDbAuditRepositoryTests
{
    private readonly Mock<IAmazonDynamoDB> _mockDynamoDb;
    private readonly Mock<ILogger<DynamoDbAuditRepository>> _mockLogger;
    private readonly IOptions<AwsSettings> _options;
    private readonly DynamoDbAuditRepository _repository;

    public DynamoDbAuditRepositoryTests()
    {
        _mockDynamoDb = new Mock<IAmazonDynamoDB>();
        _mockLogger = new Mock<ILogger<DynamoDbAuditRepository>>();
        _options = Options.Create(new AwsSettings
        {
            DynamoDbTable = "test-audit-events",
            Region = "us-east-1",
        });

        _repository = new DynamoDbAuditRepository(
            _mockDynamoDb.Object,
            _options,
            Options.Create(new AuditLimits { ScanPageSize = 2, MaxQueryWindow = 100 }),
            _mockLogger.Object);
    }

    [Fact]
    public async Task SaveEventAsync_ShouldCallPutItem()
    {
        var auditEvent = new AuditEvent
        {
            Id = "test-id",
            UserId = "user-1",
            Action = "create",
            ResourceType = "document",
            ResourceId = "doc-1",
            Timestamp = DateTime.UtcNow,
            IpAddress = "10.0.0.1",
            UserAgent = "TestAgent",
            Details = new Dictionary<string, string> { ["key"] = "value" },
        };

        _mockDynamoDb
            .Setup(d => d.PutItemAsync(It.IsAny<PutItemRequest>(), default))
            .ReturnsAsync(new PutItemResponse());

        await _repository.SaveEventAsync(auditEvent);

        _mockDynamoDb.Verify(d => d.PutItemAsync(It.Is<PutItemRequest>(req =>
            req.TableName == "test-audit-events" &&
            req.Item["Id"].S == "test-id" &&
            req.Item["UserId"].S == "user-1" &&
            req.Item["Action"].S == "create" &&
            req.Item["ResourceType"].S == "document" &&
            req.Item["ResourceId"].S == "doc-1" &&
            req.Item["IpAddress"].S == "10.0.0.1" &&
            req.Item["UserAgent"].S == "TestAgent" &&
            req.Item["Details"].M["key"].S == "value"),
            default), Times.Once);
    }

    [Fact]
    public async Task SaveEventAsync_WithNullOptionalFields_ShouldNotIncludeThem()
    {
        var auditEvent = new AuditEvent
        {
            Id = "test-id",
            UserId = "user-1",
            Action = "create",
            ResourceType = "document",
            ResourceId = "doc-1",
            Timestamp = DateTime.UtcNow,
        };

        _mockDynamoDb
            .Setup(d => d.PutItemAsync(It.IsAny<PutItemRequest>(), default))
            .ReturnsAsync(new PutItemResponse());

        await _repository.SaveEventAsync(auditEvent);

        _mockDynamoDb.Verify(d => d.PutItemAsync(It.Is<PutItemRequest>(req =>
            !req.Item.ContainsKey("IpAddress") &&
            !req.Item.ContainsKey("UserAgent") &&
            !req.Item.ContainsKey("Details")),
            default), Times.Once);
    }

    [Fact]
    public async Task GetEventAsync_WhenItemExists_ShouldReturnEvent()
    {
        var item = CreateDynamoDbItem("test-id", "user-1", "create", "document", "doc-1");
        _mockDynamoDb
            .Setup(d => d.GetItemAsync(It.IsAny<GetItemRequest>(), default))
            .ReturnsAsync(new GetItemResponse { Item = item });

        var result = await _repository.GetEventAsync("test-id");

        Assert.NotNull(result);
        Assert.Equal("test-id", result.Id);
        Assert.Equal("user-1", result.UserId);
        Assert.Equal("create", result.Action);
    }

    [Fact]
    public async Task GetEventAsync_WhenItemNotFound_ShouldReturnNull()
    {
        _mockDynamoDb
            .Setup(d => d.GetItemAsync(It.IsAny<GetItemRequest>(), default))
            .ReturnsAsync(new GetItemResponse { Item = new Dictionary<string, AttributeValue>() });

        var result = await _repository.GetEventAsync("nonexistent");

        Assert.Null(result);
    }

    [Fact]
    public async Task QueryEventsAsync_ShouldReturnNewestPageWithTotal()
    {
        var now = DateTime.UtcNow;
        var items = new[]
        {
            CreateDynamoDbItem("e1", "user-1", "create", "document", "doc-1", now.AddMinutes(-3)),
            CreateDynamoDbItem("e2", "user-1", "update", "document", "doc-2", now.AddMinutes(-1)),
            CreateDynamoDbItem("e3", "user-1", "delete", "document", "doc-3", now.AddMinutes(-2)),
        };
        SetupScanPages(items[..2], items[2..]);
        var requestedKeys = SetupBatchGet(items);

        var result = await _repository.QueryEventsAsync("user-1", null, null, null, null, null, 1, 2);

        Assert.Equal(3, result.Total);
        Assert.Equal(new[] { "e2", "e3" }, result.Events.Select(e => e.Id));
        Assert.Equal(1, result.Page);
        Assert.Equal(2, result.PageSize);
        Assert.Equal(new[] { "e2", "e3" }, requestedKeys);
    }

    [Fact]
    public async Task QueryEventsAsync_SecondPage_ShouldReturnRemainingEvents()
    {
        var now = DateTime.UtcNow;
        var items = new[]
        {
            CreateDynamoDbItem("e1", "user-1", "create", "document", "doc-1", now.AddMinutes(-3)),
            CreateDynamoDbItem("e2", "user-1", "update", "document", "doc-2", now.AddMinutes(-1)),
            CreateDynamoDbItem("e3", "user-1", "delete", "document", "doc-3", now.AddMinutes(-2)),
        };
        SetupScanPages(items);
        SetupBatchGet(items);

        var result = await _repository.QueryEventsAsync("user-1", null, null, null, null, null, 2, 2);

        Assert.Equal(3, result.Total);
        Assert.Equal(new[] { "e1" }, result.Events.Select(e => e.Id));
    }

    [Fact]
    public async Task QueryEventsAsync_ShouldScanKeysOnlyWithLimitAndCursor()
    {
        var now = DateTime.UtcNow;
        var items = Enumerable.Range(1, 50)
            .Select(i => CreateDynamoDbItem($"e{i}", "user-1", "create", "document", "doc-1", now.AddMinutes(-i)))
            .ToArray();
        var (requests, startKeys) = SetupScanPages(items.Chunk(2).ToArray());
        var requestedKeys = SetupBatchGet(items);

        var result = await _repository.QueryEventsAsync(null, null, null, null, null, null, 1, 5);

        Assert.Equal(50, result.Total);
        Assert.Equal(new[] { "e1", "e2", "e3", "e4", "e5" }, result.Events.Select(e => e.Id));
        Assert.Equal(5, requestedKeys.Count);
        Assert.Equal(25, startKeys.Count);
        Assert.Null(startKeys[0]);
        Assert.All(startKeys.Skip(1), k => Assert.NotNull(k));
        Assert.All(requests, r =>
        {
            Assert.Equal(2, r.Limit);
            Assert.Equal("#pk, #ts", r.ProjectionExpression);
        });
    }

    [Fact]
    public async Task QueryEventsAsync_WithFilters_ShouldApplyFilterExpression()
    {
        SetupScanPages(Array.Empty<Dictionary<string, AttributeValue>>());

        await _repository.QueryEventsAsync("user-1", "create", "document", "doc-1", null, null, 1, 20);

        _mockDynamoDb.Verify(d => d.ScanAsync(It.Is<ScanRequest>(req =>
            req.FilterExpression != null &&
            req.FilterExpression.Contains("#uid = :uid") &&
            req.FilterExpression.Contains("#act = :act") &&
            req.FilterExpression.Contains("ResourceType = :rt") &&
            req.FilterExpression.Contains("ResourceId = :rid") &&
            req.Limit == 2),
            It.IsAny<CancellationToken>()), Times.Once);
        _mockDynamoDb.Verify(d => d.BatchGetItemAsync(It.IsAny<BatchGetItemRequest>(), It.IsAny<CancellationToken>()), Times.Never);
    }

    [Fact]
    public async Task StreamUserEventsAsync_ShouldFilterByUserIdAndRange()
    {
        var from = DateTime.UtcNow.AddDays(-30);
        var to = DateTime.UtcNow;
        var (requests, _) = SetupScanPages(new[] { CreateDynamoDbItem("e1", "user-1", "create", "document", "doc-1") });

        var result = await ToListAsync(_repository.StreamUserEventsAsync("user-1", from, to));

        Assert.Single(result);
        Assert.Equal("user-1", result[0].UserId);
        var request = Assert.Single(requests);
        Assert.Equal("#uid = :uid AND #ts >= :fromTs AND #ts <= :toTs", request.FilterExpression);
        Assert.Equal("user-1", request.ExpressionAttributeValues[":uid"].S);
        Assert.Equal(2, request.Limit);
    }

    [Fact]
    public async Task GetResourceHistoryAsync_ShouldReturnNewestEventsUpToLimit()
    {
        var now = DateTime.UtcNow;
        var items = new[]
        {
            CreateDynamoDbItem("e1", "user-1", "create", "document", "doc-1", now.AddMinutes(-3)),
            CreateDynamoDbItem("e2", "user-2", "update", "document", "doc-1", now.AddMinutes(-1)),
            CreateDynamoDbItem("e3", "user-2", "update", "document", "doc-1", now.AddMinutes(-2)),
        };
        SetupScanPages(items);
        SetupBatchGet(items);

        var result = await _repository.GetResourceHistoryAsync("doc-1", 2);

        Assert.Equal(3, result.Total);
        Assert.Equal(new[] { "e2", "e3" }, result.Events.Select(e => e.Id));

        _mockDynamoDb.Verify(d => d.ScanAsync(It.Is<ScanRequest>(req =>
            req.FilterExpression == "ResourceId = :rid" &&
            req.ExpressionAttributeValues[":rid"].S == "doc-1"),
            It.IsAny<CancellationToken>()), Times.Once);
    }

    [Fact]
    public async Task DeleteEventsAsync_ShouldBatchDeleteInGroupsOf25()
    {
        var eventIds = Enumerable.Range(1, 30).Select(i => $"event-{i}").ToList();

        _mockDynamoDb
            .Setup(d => d.BatchWriteItemAsync(It.IsAny<BatchWriteItemRequest>(), default))
            .ReturnsAsync(new BatchWriteItemResponse());

        await _repository.DeleteEventsAsync(eventIds);

        _mockDynamoDb.Verify(d => d.BatchWriteItemAsync(It.IsAny<BatchWriteItemRequest>(), default), Times.Exactly(2));
    }

    [Fact]
    public async Task StreamEventsByDateRangeAsync_ShouldPageWithLimitAndCursor()
    {
        var from = DateTime.UtcNow.AddDays(-7);
        var to = DateTime.UtcNow;
        var items = new[]
        {
            CreateDynamoDbItem("e1", "user-1", "create", "document", "doc-1"),
            CreateDynamoDbItem("e2", "user-1", "create", "document", "doc-2"),
            CreateDynamoDbItem("e3", "user-1", "create", "document", "doc-3"),
        };
        var (requests, startKeys) = SetupScanPages(items[..2], items[2..]);

        var result = await ToListAsync(_repository.StreamEventsByDateRangeAsync(from, to));

        Assert.Equal(new[] { "e1", "e2", "e3" }, result.Select(e => e.Id));
        Assert.Equal(2, startKeys.Count);
        Assert.Null(startKeys[0]);
        Assert.Equal("e2", startKeys[1]!["id"].S);
        Assert.All(requests, r =>
        {
            Assert.Equal("#ts >= :fromTs AND #ts <= :toTs", r.FilterExpression);
            Assert.Equal("Timestamp", r.ExpressionAttributeNames["#ts"]);
            Assert.Equal(2, r.Limit);
        });
    }

    [Fact]
    public async Task StreamEventsByDateRangeAsync_ShouldStopScanningWhenConsumerStops()
    {
        var items = Enumerable.Range(1, 10)
            .Select(i => CreateDynamoDbItem($"e{i}", "user-1", "create", "document", "doc-1"))
            .ToArray();
        var (requests, _) = SetupScanPages(items.Chunk(2).ToArray());

        await foreach (var _ in _repository.StreamEventsByDateRangeAsync(DateTime.MinValue, DateTime.UtcNow))
            break;

        Assert.Single(requests);
    }

    private (List<ScanRequest> Requests, List<Dictionary<string, AttributeValue>?> StartKeys) SetupScanPages(
        params Dictionary<string, AttributeValue>[][] pages)
    {
        var requests = new List<ScanRequest>();
        var startKeys = new List<Dictionary<string, AttributeValue>?>();
        var call = 0;

        _mockDynamoDb
            .Setup(d => d.ScanAsync(It.IsAny<ScanRequest>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync((ScanRequest req, CancellationToken _) =>
            {
                requests.Add(req);
                startKeys.Add(req.ExclusiveStartKey?.Count > 0 ? new Dictionary<string, AttributeValue>(req.ExclusiveStartKey) : null);
                var page = pages.Length == 0 ? Array.Empty<Dictionary<string, AttributeValue>>() : pages[call];
                var isLast = call >= pages.Length - 1;
                call++;
                return new ScanResponse
                {
                    Items = page.ToList(),
                    LastEvaluatedKey = isLast
                        ? new Dictionary<string, AttributeValue>()
                        : new Dictionary<string, AttributeValue> { ["id"] = page[^1]["id"] },
                };
            });

        return (requests, startKeys);
    }

    private List<string> SetupBatchGet(IEnumerable<Dictionary<string, AttributeValue>> items)
    {
        var lookup = items.ToDictionary(i => i["id"].S);
        var requested = new List<string>();

        _mockDynamoDb
            .Setup(d => d.BatchGetItemAsync(It.IsAny<BatchGetItemRequest>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync((BatchGetItemRequest req, CancellationToken _) =>
            {
                var keys = req.RequestItems["test-audit-events"].Keys.Select(k => k["id"].S).ToList();
                requested.AddRange(keys);
                return new BatchGetItemResponse
                {
                    Responses = new Dictionary<string, List<Dictionary<string, AttributeValue>>>
                    {
                        ["test-audit-events"] = keys.Select(k => lookup[k]).Reverse().ToList(),
                    },
                    UnprocessedKeys = new Dictionary<string, KeysAndAttributes>(),
                };
            });

        return requested;
    }

    private static async Task<List<AuditEvent>> ToListAsync(IAsyncEnumerable<AuditEvent> source)
    {
        var list = new List<AuditEvent>();
        await foreach (var item in source)
            list.Add(item);
        return list;
    }

    private static Dictionary<string, AttributeValue> CreateDynamoDbItem(
        string id, string userId, string action, string resourceType, string resourceId, DateTime? timestamp = null)
    {
        return new Dictionary<string, AttributeValue>
        {
            ["id"] = new AttributeValue { S = id },
            ["Id"] = new AttributeValue { S = id },
            ["UserId"] = new AttributeValue { S = userId },
            ["Action"] = new AttributeValue { S = action },
            ["ResourceType"] = new AttributeValue { S = resourceType },
            ["ResourceId"] = new AttributeValue { S = resourceId },
            ["Timestamp"] = new AttributeValue { S = (timestamp ?? DateTime.UtcNow).ToString("O") },
        };
    }
}
