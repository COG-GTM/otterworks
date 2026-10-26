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
    public async Task SaveEventAsync_ShouldWriteIndexKeyAttributes()
    {
        var auditEvent = new AuditEvent
        {
            Id = "test-id",
            UserId = "user-1",
            Action = "create",
            ResourceType = "document",
            ResourceId = "doc-1",
            Timestamp = new DateTime(2026, 3, 4, 5, 6, 7, DateTimeKind.Utc),
        };

        _mockDynamoDb
            .Setup(d => d.PutItemAsync(It.IsAny<PutItemRequest>(), default))
            .ReturnsAsync(new PutItemResponse());

        await _repository.SaveEventAsync(auditEvent);

        _mockDynamoDb.Verify(d => d.PutItemAsync(It.Is<PutItemRequest>(req =>
            req.Item["user_id"].S == "user-1" &&
            req.Item["timestamp"].S == "2026-03-04T05:06:07.0000000Z" &&
            req.Item["date_partition"].S == "2026-03-04"),
            default), Times.Once);
    }

    [Fact]
    public async Task QueryEventsAsync_WithUserId_ShouldQueryUserIndexWithLimit()
    {
        var items = new List<Dictionary<string, AttributeValue>>
        {
            CreateDynamoDbItem("e1", "user-1", "create", "document", "doc-1"),
            CreateDynamoDbItem("e2", "user-1", "update", "document", "doc-2"),
        };
        var captured = SetupQuery(_ => new QueryResponse
        {
            Items = items,
            LastEvaluatedKey = UserIndexKey("e2", "user-1"),
        });

        var result = await _repository.QueryEventsAsync("user-1", null, null, null, null, null, 1, 2, null);

        Assert.Equal(2, result.Total);
        Assert.Equal(2, result.Events.Count);
        Assert.Equal(1, result.Page);
        Assert.Equal(2, result.PageSize);
        Assert.True(result.HasMore);
        Assert.NotNull(result.NextCursor);

        var request = Assert.Single(captured);
        Assert.Equal("test-audit-events", request.TableName);
        Assert.Equal("user-index", request.IndexName);
        Assert.Equal("#pk = :pk AND #ts BETWEEN :fromTs AND :toTs", request.KeyConditionExpression);
        Assert.Equal("user_id", request.ExpressionAttributeNames["#pk"]);
        Assert.Equal("timestamp", request.ExpressionAttributeNames["#ts"]);
        Assert.Equal("user-1", request.ExpressionAttributeValues[":pk"].S);
        Assert.Equal(2, request.Limit);
        Assert.False(request.ScanIndexForward);
        VerifyNoScan();
    }

    [Fact]
    public async Task QueryEventsAsync_WithFilters_ShouldApplyFilterExpressionToQuery()
    {
        var captured = SetupQuery(_ => new QueryResponse());

        await _repository.QueryEventsAsync("user-1", "create", "document", "doc-1", null, null, 1, 20, null);

        var request = Assert.Single(captured);
        Assert.Equal("#act = :act AND #rt = :rt AND #rid = :rid", request.FilterExpression);
        Assert.Equal("Action", request.ExpressionAttributeNames["#act"]);
        Assert.Equal("ResourceType", request.ExpressionAttributeNames["#rt"]);
        Assert.Equal("ResourceId", request.ExpressionAttributeNames["#rid"]);
        Assert.Equal("create", request.ExpressionAttributeValues[":act"].S);
        Assert.Equal("document", request.ExpressionAttributeValues[":rt"].S);
        Assert.Equal("doc-1", request.ExpressionAttributeValues[":rid"].S);
        VerifyNoScan();
    }

    [Fact]
    public async Task QueryEventsAsync_Unfiltered_ShouldQueryDatePartitionsNewestFirst()
    {
        var captured = SetupQuery(_ => new QueryResponse());
        var from = new DateTime(2026, 1, 1, 0, 0, 0, DateTimeKind.Utc);
        var to = new DateTime(2026, 1, 3, 12, 0, 0, DateTimeKind.Utc);

        var result = await _repository.QueryEventsAsync(null, null, null, null, from, to, 1, 20, null);

        Assert.Empty(result.Events);
        Assert.False(result.HasMore);
        Assert.Null(result.NextCursor);
        Assert.Equal(new[] { "2026-01-03", "2026-01-02", "2026-01-01" },
            captured.Select(r => r.ExpressionAttributeValues[":pk"].S));
        Assert.All(captured, r =>
        {
            Assert.Equal("timestamp-index", r.IndexName);
            Assert.Equal("date_partition", r.ExpressionAttributeNames["#pk"]);
            Assert.Equal("2026-01-01T00:00:00.0000000Z", r.ExpressionAttributeValues[":fromTs"].S);
            Assert.Equal("2026-01-03T12:00:00.0000000Z", r.ExpressionAttributeValues[":toTs"].S);
        });
        VerifyNoScan();
    }

    [Fact]
    public async Task QueryEventsAsync_Unfiltered_OnLargeTable_ShouldMakeOneCallAndReturnCursor()
    {
        var calls = 0;
        SetupQuery(req =>
        {
            calls++;
            var items = Enumerable.Range(0, req.Limit)
                .Select(i => CreateDynamoDbItem($"e{calls}-{i}", "user-1", "create", "document", "doc-1"))
                .ToList();
            return new QueryResponse
            {
                Items = items,
                LastEvaluatedKey = DateIndexKey($"e{calls}-last", req.ExpressionAttributeValues[":pk"].S),
            };
        });

        var result = await _repository.QueryEventsAsync(null, null, null, null, null, null, 1, 20, null);

        Assert.Equal(1, calls);
        Assert.Equal(20, result.Events.Count);
        Assert.True(result.HasMore);
        Assert.False(string.IsNullOrEmpty(result.NextCursor));
        VerifyNoScan();
    }

    [Fact]
    public async Task QueryEventsAsync_WhenFilterMatchesNothing_ShouldStopAfterCallBudget()
    {
        var calls = 0;
        SetupQuery(req =>
        {
            calls++;
            return new QueryResponse
            {
                LastEvaluatedKey = DateIndexKey($"e{calls}", req.ExpressionAttributeValues[":pk"].S),
            };
        });

        var result = await _repository.QueryEventsAsync(null, "no-such-action", null, null, null, null, 1, 20, null);

        Assert.Equal(AuditQueryLimits.MaxCallsPerPage, calls);
        Assert.Empty(result.Events);
        Assert.True(result.HasMore);
        Assert.NotNull(result.NextCursor);
    }

    [Fact]
    public async Task QueryEventsAsync_WithCursor_ShouldResumeFromExclusiveStartKey()
    {
        var lastKey = UserIndexKey("e2", "user-1");
        var captured = SetupQuery(req => req.ExclusiveStartKey?.Count > 0
            ? new QueryResponse { Items = new() { CreateDynamoDbItem("e3", "user-1", "create", "document", "doc-3") } }
            : new QueryResponse
            {
                Items = new()
                {
                    CreateDynamoDbItem("e1", "user-1", "create", "document", "doc-1"),
                    CreateDynamoDbItem("e2", "user-1", "create", "document", "doc-2"),
                },
                LastEvaluatedKey = lastKey,
            });

        var first = await _repository.QueryEventsAsync("user-1", "create", null, null, null, null, 1, 2, null);
        var second = await _repository.QueryEventsAsync("user-1", "create", null, null, null, null, 1, 2, first.NextCursor);

        Assert.Equal(2, captured.Count);
        Assert.Equal(lastKey.Keys.OrderBy(k => k), captured[1].ExclusiveStartKey.Keys.OrderBy(k => k));
        Assert.All(lastKey, kvp => Assert.Equal(kvp.Value.S, captured[1].ExclusiveStartKey[kvp.Key].S));
        Assert.Equal(captured[0].ExpressionAttributeValues[":fromTs"].S, captured[1].ExpressionAttributeValues[":fromTs"].S);
        Assert.Equal(captured[0].ExpressionAttributeValues[":toTs"].S, captured[1].ExpressionAttributeValues[":toTs"].S);
        Assert.Equal("e3", Assert.Single(second.Events).Id);
        Assert.False(second.HasMore);
        Assert.Null(second.NextCursor);
    }

    [Fact]
    public async Task QueryEventsAsync_WithCursorFromDifferentQuery_ShouldReject()
    {
        SetupQuery(_ => new QueryResponse
        {
            Items = new() { CreateDynamoDbItem("e1", "user-1", "create", "document", "doc-1") },
            LastEvaluatedKey = UserIndexKey("e1", "user-1"),
        });

        var first = await _repository.QueryEventsAsync("user-1", null, null, null, null, null, 1, 1, null);

        await Assert.ThrowsAsync<AuditQueryException>(() =>
            _repository.QueryEventsAsync("user-2", null, null, null, null, null, 1, 1, first.NextCursor));
    }

    [Theory]
    [InlineData("not-a-cursor!!")]
    [InlineData("eyJIIjoiIn0")]
    public async Task QueryEventsAsync_WithMalformedCursor_ShouldReject(string cursor)
    {
        await Assert.ThrowsAsync<AuditQueryException>(() =>
            _repository.QueryEventsAsync(null, null, null, null, null, null, 1, 20, cursor));
        VerifyNoQuery();
    }

    [Fact]
    public async Task QueryEventsAsync_WithRangeAboveCap_ShouldReject()
    {
        await Assert.ThrowsAsync<AuditQueryException>(() =>
            _repository.QueryEventsAsync(null, null, null, null,
                new DateTime(1, 1, 1, 0, 0, 0, DateTimeKind.Utc),
                new DateTime(9999, 12, 31, 0, 0, 0, DateTimeKind.Utc), 1, 20, null));
        VerifyNoQuery();
    }

    [Fact]
    public async Task QueryEventsAsync_WithDeepPageOffset_ShouldReject()
    {
        await Assert.ThrowsAsync<AuditQueryException>(() =>
            _repository.QueryEventsAsync(null, null, null, null, null, null, 1000, 100, null));
        VerifyNoQuery();
    }

    [Fact]
    public async Task QueryEventsAsync_SecondPage_ShouldSkipFirstPage()
    {
        var captured = SetupQuery(req => new QueryResponse
        {
            Items = Enumerable.Range(1, req.Limit)
                .Select(i => CreateDynamoDbItem($"e{i}", "user-1", "create", "document", "doc-1"))
                .ToList(),
        });

        var result = await _repository.QueryEventsAsync("user-1", null, null, null, null, null, 2, 2, null);

        Assert.Equal(4, Assert.Single(captured).Limit);
        Assert.Equal(new[] { "e3", "e4" }, result.Events.Select(e => e.Id));
    }

    [Fact]
    public async Task GetUserEventsAsync_ShouldQueryUserIndexAndCapResults()
    {
        var captured = SetupQuery(req => new QueryResponse
        {
            Items = Enumerable.Range(0, req.Limit)
                .Select(i => CreateDynamoDbItem($"e{i}", "user-1", "create", "document", "doc-1"))
                .ToList(),
            LastEvaluatedKey = UserIndexKey("next", "user-1"),
        });

        var result = await _repository.GetUserEventsAsync("user-1", DateTime.UtcNow.AddDays(-365), DateTime.UtcNow, 5);

        Assert.Equal(5, result.Events.Count);
        Assert.True(result.Truncated);
        var request = Assert.Single(captured);
        Assert.Equal("user-index", request.IndexName);
        Assert.Equal("user-1", request.ExpressionAttributeValues[":pk"].S);
        VerifyNoScan();
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
    public async Task GetEventsByDateRangeAsync_ShouldQueryEachDayPartition()
    {
        var from = new DateTime(2026, 2, 1, 0, 0, 0, DateTimeKind.Utc);
        var to = new DateTime(2026, 2, 7, 0, 0, 0, DateTimeKind.Utc);
        var captured = SetupQuery(_ => new QueryResponse());

        var result = await _repository.GetEventsByDateRangeAsync(from, to, 100);

        Assert.Empty(result.Events);
        Assert.False(result.Truncated);
        Assert.Equal(7, captured.Count);
        Assert.All(captured, r => Assert.Equal("timestamp-index", r.IndexName));
        VerifyNoScan();
    }

    [Fact]
    public async Task GetEventsByDateRangeAsync_FromMinValue_ShouldStopAtCallBudget()
    {
        var captured = SetupQuery(_ => new QueryResponse());

        var result = await _repository.GetEventsByDateRangeAsync(DateTime.MinValue, DateTime.UtcNow, 100);

        Assert.Equal(AuditQueryLimits.MaxCallsPerCollection, captured.Count);
        Assert.True(result.Truncated);
        VerifyNoScan();
    }

    private List<QueryRequest> SetupQuery(Func<QueryRequest, QueryResponse> respond)
    {
        var captured = new List<QueryRequest>();
        _mockDynamoDb
            .Setup(d => d.QueryAsync(It.IsAny<QueryRequest>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync((QueryRequest req, CancellationToken _) =>
            {
                captured.Add(req);
                return respond(req);
            });
        return captured;
    }

    private void VerifyNoScan() =>
        _mockDynamoDb.Verify(d => d.ScanAsync(It.IsAny<ScanRequest>(), It.IsAny<CancellationToken>()), Times.Never);

    private void VerifyNoQuery() =>
        _mockDynamoDb.Verify(d => d.QueryAsync(It.IsAny<QueryRequest>(), It.IsAny<CancellationToken>()), Times.Never);

    private static Dictionary<string, AttributeValue> UserIndexKey(string id, string userId) => new()
    {
        ["id"] = new AttributeValue { S = id },
        ["user_id"] = new AttributeValue { S = userId },
        ["timestamp"] = new AttributeValue { S = "2026-01-01T00:00:00.0000000Z" },
    };

    private static Dictionary<string, AttributeValue> DateIndexKey(string id, string datePartition) => new()
    {
        ["id"] = new AttributeValue { S = id },
        ["date_partition"] = new AttributeValue { S = datePartition },
        ["timestamp"] = new AttributeValue { S = datePartition + "T00:00:00.0000000Z" },
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
