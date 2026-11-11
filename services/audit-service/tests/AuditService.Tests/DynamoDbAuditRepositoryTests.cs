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
            _mockDynamoDb.Object, _options, Options.Create(new AuditQuerySettings()), _mockLogger.Object);
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
    public async Task SaveEventAsync_ShouldWriteIndexKeyAttributes()
    {
        var auditEvent = new AuditEvent
        {
            Id = "test-id",
            UserId = "user-1",
            Action = "create",
            ResourceType = "document",
            ResourceId = "doc-1",
            Timestamp = new DateTime(2026, 11, 11, 18, 0, 0, DateTimeKind.Utc),
        };

        _mockDynamoDb
            .Setup(d => d.PutItemAsync(It.IsAny<PutItemRequest>(), default))
            .ReturnsAsync(new PutItemResponse());

        await _repository.SaveEventAsync(auditEvent);

        _mockDynamoDb.Verify(d => d.PutItemAsync(It.Is<PutItemRequest>(req =>
            req.Item["user_id"].S == "user-1" &&
            req.Item["timestamp"].S == "2026-11-11T18:00:00.0000000Z" &&
            req.Item["date_partition"].S == "2026-11-11"),
            default), Times.Once);
    }

    [Fact]
    public async Task QueryEventsAsync_WithUser_ShouldQueryUserIndexWithNativeLimitAndReturnCursor()
    {
        var lastKey = UserIndexKey("e2", "user-1");
        _mockDynamoDb
            .Setup(d => d.QueryAsync(It.IsAny<QueryRequest>(), default))
            .ReturnsAsync(new QueryResponse
            {
                Items = new List<Dictionary<string, AttributeValue>>
                {
                    CreateDynamoDbItem("e1", "user-1", "create", "document", "doc-1"),
                    CreateDynamoDbItem("e2", "user-1", "update", "document", "doc-2"),
                },
                LastEvaluatedKey = lastKey,
            });

        var result = await _repository.QueryEventsAsync("user-1", "create", "document", "doc-1", null, null, null, 2);

        Assert.Equal(2, result.Events.Count);
        Assert.Equal(2, result.Total);
        Assert.NotNull(result.NextCursor);
        _mockDynamoDb.Verify(d => d.ScanAsync(It.IsAny<ScanRequest>(), default), Times.Never);
        _mockDynamoDb.Verify(d => d.QueryAsync(It.Is<QueryRequest>(req =>
            req.IndexName == "user-index" &&
            req.Limit == 2 &&
            req.ScanIndexForward == false &&
            req.KeyConditionExpression == "#guid = :guid" &&
            req.ExpressionAttributeValues[":guid"].S == "user-1" &&
            req.FilterExpression.Contains("#act = :act") &&
            req.FilterExpression.Contains("ResourceType = :rt") &&
            req.FilterExpression.Contains("ResourceId = :rid")),
            default), Times.Once);

        var captured = new List<QueryRequest>();
        _mockDynamoDb.Invocations.Clear();
        _mockDynamoDb
            .Setup(d => d.QueryAsync(Capture.In(captured), default))
            .ReturnsAsync(new QueryResponse { Items = new(), LastEvaluatedKey = new() });

        var next = await _repository.QueryEventsAsync("user-1", "create", "document", "doc-1", null, null, result.NextCursor, 2);

        Assert.Null(next.NextCursor);
        Assert.Single(captured);
        Assert.Equal("e2", captured[0].ExclusiveStartKey["id"].S);
    }

    [Fact]
    public async Task QueryEventsAsync_ShouldBoundDynamoCallsPerPage()
    {
        _mockDynamoDb
            .Setup(d => d.QueryAsync(It.IsAny<QueryRequest>(), default))
            .ReturnsAsync(() => new QueryResponse
            {
                Items = new List<Dictionary<string, AttributeValue>>(),
                LastEvaluatedKey = UserIndexKey("e1", "user-1"),
            });

        var result = await _repository.QueryEventsAsync("user-1", null, null, null, null, null, null, 20);

        Assert.Empty(result.Events);
        Assert.NotNull(result.NextCursor);
        _mockDynamoDb.Verify(d => d.QueryAsync(It.IsAny<QueryRequest>(), default), Times.Exactly(10));
    }

    [Fact]
    public async Task QueryEventsAsync_WithoutUser_ShouldWalkDatePartitionsWithinBoundedCalls()
    {
        var captured = new List<QueryRequest>();
        _mockDynamoDb
            .Setup(d => d.QueryAsync(Capture.In(captured), default))
            .ReturnsAsync(() => new QueryResponse { Items = new(), LastEvaluatedKey = new() });

        var to = new DateTime(2026, 11, 30, 12, 0, 0, DateTimeKind.Utc);
        var from = to.AddDays(-29);
        var result = await _repository.QueryEventsAsync(null, null, null, null, from, to, null, 20);

        Assert.Equal(10, captured.Count);
        Assert.All(captured, req => Assert.Equal("timestamp-index", req.IndexName));
        Assert.Equal("2026-11-30", captured[0].ExpressionAttributeValues[":gdp"].S);
        Assert.Equal("2026-11-21", captured[9].ExpressionAttributeValues[":gdp"].S);
        Assert.NotNull(result.NextCursor);

        captured.Clear();
        var next = await _repository.QueryEventsAsync(null, null, null, null, from, to, result.NextCursor, 20);

        Assert.Equal("2026-11-20", captured[0].ExpressionAttributeValues[":gdp"].S);
        Assert.NotNull(next.NextCursor);
    }

    [Fact]
    public async Task QueryEventsAsync_WithRangeAboveLimit_ShouldThrow()
    {
        await Assert.ThrowsAsync<ArgumentException>(() => _repository.QueryEventsAsync(
            null, null, null, null, new DateTime(1, 1, 1), new DateTime(9999, 12, 31), null, 20));
        _mockDynamoDb.Verify(d => d.QueryAsync(It.IsAny<QueryRequest>(), default), Times.Never);
    }

    [Fact]
    public async Task QueryEventsAsync_WithCursorForAnotherUser_ShouldThrow()
    {
        _mockDynamoDb
            .Setup(d => d.QueryAsync(It.IsAny<QueryRequest>(), default))
            .ReturnsAsync(new QueryResponse
            {
                Items = new List<Dictionary<string, AttributeValue>>
                {
                    CreateDynamoDbItem("e1", "user-1", "create", "document", "doc-1"),
                },
                LastEvaluatedKey = UserIndexKey("e1", "user-1"),
            });
        var page = await _repository.QueryEventsAsync("user-1", null, null, null, null, null, null, 1);

        await Assert.ThrowsAsync<ArgumentException>(() =>
            _repository.QueryEventsAsync("user-2", null, null, null, null, null, page.NextCursor, 1));
        await Assert.ThrowsAsync<ArgumentException>(() =>
            _repository.QueryEventsAsync("user-1", null, null, null, null, null, "not-a-cursor!", 1));
    }

    [Fact]
    public async Task GetUserEventsAsync_ShouldQueryUserIndexAndCapItems()
    {
        _mockDynamoDb
            .Setup(d => d.QueryAsync(It.IsAny<QueryRequest>(), default))
            .ReturnsAsync(new QueryResponse
            {
                Items = new List<Dictionary<string, AttributeValue>>
                {
                    CreateDynamoDbItem("e1", "user-1", "create", "document", "doc-1"),
                    CreateDynamoDbItem("e2", "user-1", "create", "document", "doc-1"),
                },
                LastEvaluatedKey = UserIndexKey("e2", "user-1"),
            });

        var result = await _repository.GetUserEventsAsync("user-1", DateTime.UtcNow.AddDays(-30), DateTime.UtcNow, 2);

        Assert.Equal(2, result.Events.Count);
        Assert.True(result.Truncated);
        _mockDynamoDb.Verify(d => d.QueryAsync(It.Is<QueryRequest>(req =>
            req.IndexName == "user-index" &&
            req.Limit == 2 &&
            req.KeyConditionExpression == "#guid = :guid AND #gts BETWEEN :gfrom AND :gto"),
            default), Times.Once);
    }

    [Fact]
    public async Task GetResourceHistoryAsync_ShouldQueryEachDayPartitionWithResourceFilter()
    {
        var captured = new List<QueryRequest>();
        _mockDynamoDb
            .Setup(d => d.QueryAsync(Capture.In(captured), default))
            .ReturnsAsync(() => new QueryResponse
            {
                Items = new List<Dictionary<string, AttributeValue>>
                {
                    CreateDynamoDbItem("e1", "user-1", "create", "document", "doc-1"),
                },
                LastEvaluatedKey = new(),
            });

        var to = DateTime.UtcNow;
        var result = await _repository.GetResourceHistoryAsync("doc-1", to.AddDays(-2), to, 100);

        Assert.Equal(3, captured.Count);
        Assert.Equal(3, result.Events.Count);
        Assert.False(result.Truncated);
        Assert.All(captured, req =>
        {
            Assert.Equal("timestamp-index", req.IndexName);
            Assert.Equal("ResourceId = :rid", req.FilterExpression);
            Assert.Equal("doc-1", req.ExpressionAttributeValues[":rid"].S);
        });
        _mockDynamoDb.Verify(d => d.ScanAsync(It.IsAny<ScanRequest>(), default), Times.Never);
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
    public async Task GetEventsByDateRangeAsync_ShouldQueryDatePartitionsOldestFirst()
    {
        var captured = new List<QueryRequest>();
        _mockDynamoDb
            .Setup(d => d.QueryAsync(Capture.In(captured), default))
            .ReturnsAsync(() => new QueryResponse { Items = new(), LastEvaluatedKey = new() });

        var from = new DateTime(2026, 11, 1, 0, 0, 0, DateTimeKind.Utc);
        var to = new DateTime(2026, 11, 7, 0, 0, 0, DateTimeKind.Utc);
        await _repository.GetEventsByDateRangeAsync(from, to, 100, oldestFirst: true);

        Assert.Equal(7, captured.Count);
        Assert.Equal("2026-11-01", captured[0].ExpressionAttributeValues[":gdp"].S);
        Assert.Equal("2026-11-07", captured[6].ExpressionAttributeValues[":gdp"].S);
        Assert.All(captured, req => Assert.True(req.ScanIndexForward));
    }

    [Fact]
    public async Task GetEventsByDateRangeAsync_WithUnboundedRange_ShouldThrow()
    {
        await Assert.ThrowsAsync<ArgumentException>(() =>
            _repository.GetEventsByDateRangeAsync(DateTime.MinValue, DateTime.UtcNow, 100));
        _mockDynamoDb.Verify(d => d.QueryAsync(It.IsAny<QueryRequest>(), default), Times.Never);
    }

    private static Dictionary<string, AttributeValue> UserIndexKey(string id, string userId) => new()
    {
        ["id"] = new AttributeValue { S = id },
        ["user_id"] = new AttributeValue { S = userId },
        ["timestamp"] = new AttributeValue { S = DateTime.UtcNow.ToString("O") },
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
