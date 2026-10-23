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

        _repository = new DynamoDbAuditRepository(_mockDynamoDb.Object, _options, _mockLogger.Object);
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
    public async Task ReadPaths_NeverScanTheTable()
    {
        SetupQuery(new QueryResponse { Items = new List<Dictionary<string, AttributeValue>>() });

        await _repository.QueryEventsAsync(new AuditEventQuery(PageSize: 1));
        await _repository.QueryEventsAsync(new AuditEventQuery(UserId: "user-1"));
        await _repository.GetUserEventsAsync("user-1", DateTime.UtcNow.AddDays(-30), DateTime.UtcNow, 100);
        await _repository.GetResourceHistoryAsync("doc-1", null, 50);
        await _repository.GetEventsByDateRangeAsync(DateTime.UtcNow.AddDays(-7), DateTime.UtcNow, 100);

        _mockDynamoDb.Verify(d => d.ScanAsync(It.IsAny<ScanRequest>(), It.IsAny<CancellationToken>()), Times.Never);
    }

    [Fact]
    public async Task QueryEventsAsync_WithUserId_ShouldQueryUserIndexWithLimit()
    {
        var items = new List<Dictionary<string, AttributeValue>>
        {
            CreateDynamoDbItem("e1", "user-1", "create", "document", "doc-1"),
            CreateDynamoDbItem("e2", "user-1", "update", "document", "doc-2"),
        };
        var lastKey = new Dictionary<string, AttributeValue>
        {
            ["id"] = new AttributeValue { S = "e2" },
            ["user_id"] = new AttributeValue { S = "user-1" },
            ["timestamp"] = new AttributeValue { S = "2026-01-01T00:00:00.0000000Z" },
        };
        var requests = SetupQuery(new QueryResponse { Items = items, ScannedCount = 2, LastEvaluatedKey = lastKey });

        var result = await _repository.QueryEventsAsync(new AuditEventQuery(UserId: "user-1", PageSize: 2));

        Assert.Equal(2, result.Events.Count);
        Assert.Equal(2, result.PageSize);
        Assert.True(result.HasMore);
        var req = Assert.Single(requests);
        Assert.Equal("test-audit-events", req.TableName);
        Assert.Equal("user-index", req.IndexName);
        Assert.Equal("#pk = :pk AND #ts BETWEEN :fromTs AND :toTs", req.KeyConditionExpression);
        Assert.Equal("user_id", req.ExpressionAttributeNames["#pk"]);
        Assert.Equal("timestamp", req.ExpressionAttributeNames["#ts"]);
        Assert.Equal("user-1", req.ExpressionAttributeValues[":pk"].S);
        Assert.Equal(2, req.Limit);
        Assert.False(req.ScanIndexForward);
    }

    [Fact]
    public async Task QueryEventsAsync_CursorRoundTrip_ShouldResumeFromLastEvaluatedKey()
    {
        var lastKey = new Dictionary<string, AttributeValue>
        {
            ["id"] = new AttributeValue { S = "e1" },
            ["user_id"] = new AttributeValue { S = "user-1" },
            ["timestamp"] = new AttributeValue { S = "2026-01-01T00:00:00.0000000Z" },
        };
        var requests = SetupQuery(
            new QueryResponse { Items = new() { CreateDynamoDbItem("e1", "user-1", "create", "document", "doc-1") }, ScannedCount = 1, LastEvaluatedKey = lastKey },
            new QueryResponse { Items = new() { CreateDynamoDbItem("e2", "user-1", "create", "document", "doc-2") }, ScannedCount = 1 });

        var first = await _repository.QueryEventsAsync(new AuditEventQuery(UserId: "user-1", PageSize: 1));
        var second = await _repository.QueryEventsAsync(new AuditEventQuery(UserId: "user-1", PageSize: 1, Cursor: first.NextCursor));

        Assert.NotNull(first.NextCursor);
        Assert.Null(second.NextCursor);
        Assert.Equal("e2", Assert.Single(second.Events).Id);
        Assert.Equal(2, requests.Count);
        Assert.Null(requests[0].ExclusiveStartKey);
        Assert.Equal("e1", requests[1].ExclusiveStartKey["id"].S);
        Assert.Equal("user-1", requests[1].ExclusiveStartKey["user_id"].S);
    }

    [Fact]
    public async Task QueryEventsAsync_WithFilters_ShouldApplyFilterExpressionOnIndexQuery()
    {
        var requests = SetupQuery(new QueryResponse { Items = new List<Dictionary<string, AttributeValue>>() });

        await _repository.QueryEventsAsync(new AuditEventQuery("user-1", "create", "document", "doc-1"));

        var req = requests[0];
        Assert.Equal("user-index", req.IndexName);
        Assert.Equal("#f0 = :f0 AND #f1 = :f1 AND #f2 = :f2", req.FilterExpression);
        Assert.Equal("Action", req.ExpressionAttributeNames["#f0"]);
        Assert.Equal("ResourceType", req.ExpressionAttributeNames["#f1"]);
        Assert.Equal("ResourceId", req.ExpressionAttributeNames["#f2"]);
        Assert.Equal("create", req.ExpressionAttributeValues[":f0"].S);
        Assert.Equal("doc-1", req.ExpressionAttributeValues[":f2"].S);
    }

    [Fact]
    public async Task QueryEventsAsync_WithoutUser_ShouldQueryTimestampIndexByDayAndCapEvaluatedItems()
    {
        _options.Value.MaxItemsEvaluatedPerRequest = 5;
        var requests = SetupQuery(new QueryResponse { Items = new List<Dictionary<string, AttributeValue>>(), ScannedCount = 0 });
        var to = new DateTime(2026, 3, 31, 12, 0, 0, DateTimeKind.Utc);

        var result = await _repository.QueryEventsAsync(new AuditEventQuery(Action: "delete", From: to.AddDays(-30), To: to, PageSize: 100));

        Assert.Equal(5, requests.Count);
        Assert.All(requests, r => Assert.Equal("timestamp-index", r.IndexName));
        Assert.All(requests, r => Assert.Equal("date_partition", r.ExpressionAttributeNames["#pk"]));
        Assert.Equal(new[] { "2026-03-31", "2026-03-30", "2026-03-29", "2026-03-28", "2026-03-27" },
            requests.Select(r => r.ExpressionAttributeValues[":pk"].S));
        Assert.True(result.HasMore);

        var next = await _repository.QueryEventsAsync(new AuditEventQuery(Action: "delete", From: to.AddDays(-30), To: to, PageSize: 100, Cursor: result.NextCursor));
        Assert.Equal("2026-03-26", requests[5].ExpressionAttributeValues[":pk"].S);
        Assert.Null(requests[5].ExclusiveStartKey);
        Assert.True(next.HasMore);
    }

    [Fact]
    public async Task QueryEventsAsync_ShouldStopOncePageIsFull()
    {
        var page = new List<Dictionary<string, AttributeValue>>
        {
            CreateDynamoDbItem("e1", "user-1", "create", "document", "doc-1"),
        };
        var requests = SetupQuery(new QueryResponse { Items = page, ScannedCount = 1 });

        var result = await _repository.QueryEventsAsync(new AuditEventQuery(PageSize: 1));

        Assert.Single(result.Events);
        Assert.Single(requests);
        Assert.Equal(1, requests[0].Limit);
        Assert.NotNull(result.NextCursor);
    }

    [Theory]
    [InlineData("not-a-cursor!")]
    [InlineData("eyJwIjoiMjAwMC0wMS0wMSJ9")]
    public async Task QueryEventsAsync_WithInvalidOrMismatchedCursor_ShouldThrow(string cursor)
    {
        SetupQuery(new QueryResponse());

        await Assert.ThrowsAsync<InvalidAuditQueryException>(
            () => _repository.QueryEventsAsync(new AuditEventQuery(Cursor: cursor)));
    }

    [Fact]
    public async Task QueryEventsAsync_WithCursorForAnotherUser_ShouldThrow()
    {
        var lastKey = new Dictionary<string, AttributeValue>
        {
            ["id"] = new AttributeValue { S = "e1" },
            ["user_id"] = new AttributeValue { S = "user-1" },
            ["timestamp"] = new AttributeValue { S = "2026-01-01T00:00:00.0000000Z" },
        };
        SetupQuery(new QueryResponse { Items = new() { CreateDynamoDbItem("e1", "user-1", "create", "document", "doc-1") }, LastEvaluatedKey = lastKey });

        var first = await _repository.QueryEventsAsync(new AuditEventQuery(UserId: "user-1", PageSize: 1));

        await Assert.ThrowsAsync<InvalidAuditQueryException>(
            () => _repository.QueryEventsAsync(new AuditEventQuery(UserId: "user-2", PageSize: 1, Cursor: first.NextCursor)));
    }

    [Fact]
    public async Task QueryEventsAsync_WithOversizedWindow_ShouldThrow()
    {
        await Assert.ThrowsAsync<InvalidAuditQueryException>(
            () => _repository.QueryEventsAsync(new AuditEventQuery(From: DateTime.UtcNow.AddYears(-5), To: DateTime.UtcNow)));
        await Assert.ThrowsAsync<InvalidAuditQueryException>(
            () => _repository.QueryEventsAsync(new AuditEventQuery(From: DateTime.UtcNow, To: DateTime.UtcNow.AddDays(-1))));
        _mockDynamoDb.Verify(d => d.QueryAsync(It.IsAny<QueryRequest>(), It.IsAny<CancellationToken>()), Times.Never);
    }

    [Fact]
    public async Task GetUserEventsAsync_ShouldQueryUserIndexAndCapResults()
    {
        var items = new List<Dictionary<string, AttributeValue>>
        {
            CreateDynamoDbItem("e1", "user-1", "create", "document", "doc-1"),
        };
        var requests = SetupQuery(new QueryResponse { Items = items, ScannedCount = 1 });

        var result = await _repository.GetUserEventsAsync("user-1", DateTime.UtcNow.AddDays(-30), DateTime.UtcNow, 50);

        Assert.Equal("user-1", Assert.Single(result.Events).UserId);
        Assert.False(result.HasMore);
        Assert.Equal("user-index", requests[0].IndexName);
        Assert.Equal("user-1", requests[0].ExpressionAttributeValues[":pk"].S);
        Assert.Equal(50, requests[0].Limit);
    }

    [Fact]
    public async Task GetResourceHistoryAsync_WithoutResourceIndex_ShouldQueryTimestampIndexWithFilter()
    {
        var items = new List<Dictionary<string, AttributeValue>>
        {
            CreateDynamoDbItem("e1", "user-1", "create", "document", "doc-1"),
            CreateDynamoDbItem("e2", "user-2", "update", "document", "doc-1"),
        };
        var requests = SetupQuery(new QueryResponse { Items = items, ScannedCount = 2 });

        var result = await _repository.GetResourceHistoryAsync("doc-1", null, 2);

        Assert.Equal(2, result.Events.Count);
        Assert.Single(requests);
        Assert.Equal("timestamp-index", requests[0].IndexName);
        Assert.Equal("#f0 = :f0", requests[0].FilterExpression);
        Assert.Equal("ResourceId", requests[0].ExpressionAttributeNames["#f0"]);
        Assert.Equal("doc-1", requests[0].ExpressionAttributeValues[":f0"].S);
    }

    [Fact]
    public async Task GetResourceHistoryAsync_WithResourceIndex_ShouldQueryIt()
    {
        _options.Value.DynamoDbResourceIndex = "resource-index";
        var requests = SetupQuery(new QueryResponse { Items = new List<Dictionary<string, AttributeValue>>() });

        await _repository.GetResourceHistoryAsync("doc-1", null, 10);

        var req = Assert.Single(requests);
        Assert.Equal("resource-index", req.IndexName);
        Assert.Equal("resource_id", req.ExpressionAttributeNames["#pk"]);
        Assert.Equal("doc-1", req.ExpressionAttributeValues[":pk"].S);
        Assert.Null(req.FilterExpression);
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
    public async Task GetEventsByDateRangeAsync_ShouldQueryEachDayPartitionNewestFirst()
    {
        var from = new DateTime(2026, 3, 1, 0, 0, 0, DateTimeKind.Utc);
        var to = new DateTime(2026, 3, 3, 23, 0, 0, DateTimeKind.Utc);
        var requests = SetupQuery(new QueryResponse { Items = new List<Dictionary<string, AttributeValue>>() });

        var result = await _repository.GetEventsByDateRangeAsync(from, to, 100);

        Assert.False(result.HasMore);
        Assert.Equal(new[] { "2026-03-03", "2026-03-02", "2026-03-01" },
            requests.Select(r => r.ExpressionAttributeValues[":pk"].S));
        Assert.All(requests, r =>
        {
            Assert.Equal("timestamp-index", r.IndexName);
            Assert.Equal(from.ToString("O"), r.ExpressionAttributeValues[":fromTs"].S);
            Assert.Equal(to.ToString("O"), r.ExpressionAttributeValues[":toTs"].S);
        });
    }

    [Fact]
    public async Task GetEventsByDateRangeAsync_ShouldClampToMaxEventsPerReport()
    {
        _options.Value.MaxEventsPerReport = 3;
        var items = Enumerable.Range(1, 3)
            .Select(i => CreateDynamoDbItem($"e{i}", "user-1", "read", "document", "doc-1"))
            .ToList();
        var requests = SetupQuery(new QueryResponse { Items = items, ScannedCount = 3 });

        var result = await _repository.GetEventsByDateRangeAsync(DateTime.UtcNow.AddDays(-7), DateTime.UtcNow, int.MaxValue);

        Assert.Equal(3, result.Events.Count);
        Assert.True(result.HasMore);
        Assert.Single(requests);
        Assert.Equal(3, requests[0].Limit);
    }

    [Fact]
    public async Task SaveEventAsync_ShouldWriteIndexKeyAttributes()
    {
        var timestamp = new DateTime(2026, 3, 1, 10, 30, 0, DateTimeKind.Utc);
        _mockDynamoDb
            .Setup(d => d.PutItemAsync(It.IsAny<PutItemRequest>(), default))
            .ReturnsAsync(new PutItemResponse());

        await _repository.SaveEventAsync(new AuditEvent
        {
            Id = "e1", UserId = "user-1", Action = "create", ResourceType = "document", ResourceId = "doc-1", Timestamp = timestamp,
        });

        _mockDynamoDb.Verify(d => d.PutItemAsync(It.Is<PutItemRequest>(req =>
            req.Item["user_id"].S == "user-1" &&
            req.Item["resource_id"].S == "doc-1" &&
            req.Item["timestamp"].S == timestamp.ToString("O") &&
            req.Item["date_partition"].S == "2026-03-01"),
            default), Times.Once);
    }

    private List<QueryRequest> SetupQuery(params QueryResponse[] responses)
    {
        var requests = new List<QueryRequest>();
        var call = 0;
        _mockDynamoDb
            .Setup(d => d.QueryAsync(It.IsAny<QueryRequest>(), It.IsAny<CancellationToken>()))
            .Callback<QueryRequest, CancellationToken>((req, _) => requests.Add(Clone(req)))
            .ReturnsAsync(() => responses[Math.Min(call++, responses.Length - 1)]);
        return requests;
    }

    private static QueryRequest Clone(QueryRequest req) => new()
    {
        TableName = req.TableName,
        IndexName = req.IndexName,
        KeyConditionExpression = req.KeyConditionExpression,
        FilterExpression = req.FilterExpression,
        ExpressionAttributeNames = new Dictionary<string, string>(req.ExpressionAttributeNames),
        ExpressionAttributeValues = new Dictionary<string, AttributeValue>(req.ExpressionAttributeValues),
        ExclusiveStartKey = req.ExclusiveStartKey is { Count: > 0 } key ? new Dictionary<string, AttributeValue>(key) : null,
        Limit = req.Limit,
        ScanIndexForward = req.ScanIndexForward,
    };

    private static Dictionary<string, AttributeValue> CreateDynamoDbItem(
        string id, string userId, string action, string resourceType, string resourceId)
    {
        return new Dictionary<string, AttributeValue>
        {
            ["Id"] = new AttributeValue { S = id },
            ["UserId"] = new AttributeValue { S = userId },
            ["Action"] = new AttributeValue { S = action },
            ["ResourceType"] = new AttributeValue { S = resourceType },
            ["ResourceId"] = new AttributeValue { S = resourceId },
            ["Timestamp"] = new AttributeValue { S = DateTime.UtcNow.ToString("O") },
        };
    }
}
