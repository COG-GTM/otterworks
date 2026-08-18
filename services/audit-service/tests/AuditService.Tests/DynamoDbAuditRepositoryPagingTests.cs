using Amazon.DynamoDBv2;
using Amazon.DynamoDBv2.Model;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Moq;
using OtterWorks.AuditService.Config;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

public class DynamoDbAuditRepositoryPagingTests
{
    private readonly Mock<IAmazonDynamoDB> _mockDynamoDb = new();
    private readonly Mock<ILogger<DynamoDbAuditRepository>> _mockLogger = new();
    private readonly DynamoDbAuditRepository _repository;

    public DynamoDbAuditRepositoryPagingTests()
    {
        _repository = new DynamoDbAuditRepository(
            _mockDynamoDb.Object,
            Options.Create(new AwsSettings { DynamoDbTable = "test-audit-events" }),
            _mockLogger.Object);
    }

    [Fact]
    public async Task QueryEventsAsync_ShouldBuildTimestampFilters_WhenRangeSupplied()
    {
        var from = new DateTime(2026, 1, 1, 0, 0, 0, DateTimeKind.Utc);
        var to = new DateTime(2026, 2, 1, 0, 0, 0, DateTimeKind.Utc);
        ScanRequest? captured = null;
        _mockDynamoDb
            .Setup(d => d.ScanAsync(It.IsAny<ScanRequest>(), default))
            .Callback<ScanRequest, CancellationToken>((r, _) => captured = r)
            .ReturnsAsync(new ScanResponse { Items = new List<Dictionary<string, AttributeValue>>() });

        await _repository.QueryEventsAsync(null, null, null, null, from, to, 1, 20);

        Assert.NotNull(captured);
        Assert.Equal("#ts >= :fromTs AND #ts <= :toTs", captured!.FilterExpression);
        Assert.Equal("Timestamp", captured.ExpressionAttributeNames["#ts"]);
        Assert.Equal(from.ToString("O"), captured.ExpressionAttributeValues[":fromTs"].S);
        Assert.Equal(to.ToString("O"), captured.ExpressionAttributeValues[":toTs"].S);
    }

    [Fact]
    public async Task QueryEventsAsync_ShouldAddTimestampAlias_WhenOnlyUpperBoundSupplied()
    {
        var to = new DateTime(2026, 2, 1, 0, 0, 0, DateTimeKind.Utc);
        ScanRequest? captured = null;
        _mockDynamoDb
            .Setup(d => d.ScanAsync(It.IsAny<ScanRequest>(), default))
            .Callback<ScanRequest, CancellationToken>((r, _) => captured = r)
            .ReturnsAsync(new ScanResponse { Items = new List<Dictionary<string, AttributeValue>>() });

        await _repository.QueryEventsAsync(null, null, null, null, null, to, 1, 20);

        Assert.NotNull(captured);
        Assert.Equal("#ts <= :toTs", captured!.FilterExpression);
        Assert.Equal("Timestamp", captured.ExpressionAttributeNames["#ts"]);
        Assert.False(captured.ExpressionAttributeValues.ContainsKey(":fromTs"));
    }

    [Fact]
    public async Task QueryEventsAsync_ShouldFollowPagination_AndPageResults()
    {
        SetupTwoPageScan();

        var page = await _repository.QueryEventsAsync("user-1", null, null, null, null, null, 2, 2);

        Assert.Equal(3, page.Total);
        Assert.Equal(2, page.Page);
        Assert.Equal(2, page.PageSize);
        Assert.Equal("evt-1", Assert.Single(page.Events).Id);
        _mockDynamoDb.Verify(d => d.ScanAsync(It.IsAny<ScanRequest>(), default), Times.Exactly(2));
    }

    [Fact]
    public async Task GetAllUserEventsAsync_ShouldFollowPagination()
    {
        SetupTwoPageScan();

        var events = await _repository.GetAllUserEventsAsync("user-1");

        Assert.Equal(3, events.Count);
        Assert.Equal("evt-3", events[0].Id);
        _mockDynamoDb.Verify(d => d.ScanAsync(It.IsAny<ScanRequest>(), default), Times.Exactly(2));
    }

    [Fact]
    public async Task GetResourceHistoryAsync_ShouldFollowPagination()
    {
        SetupTwoPageScan();

        var events = await _repository.GetResourceHistoryAsync("resource-1");

        Assert.Equal(3, events.Count);
        Assert.Equal("evt-3", events[0].Id);
        _mockDynamoDb.Verify(d => d.ScanAsync(It.IsAny<ScanRequest>(), default), Times.Exactly(2));
    }

    [Fact]
    public async Task GetEventsByDateRangeAsync_ShouldFollowPagination()
    {
        SetupTwoPageScan();

        var events = await _repository.GetEventsByDateRangeAsync(
            new DateTime(2026, 1, 1, 0, 0, 0, DateTimeKind.Utc),
            new DateTime(2026, 2, 1, 0, 0, 0, DateTimeKind.Utc));

        Assert.Equal(3, events.Count);
        Assert.Equal("evt-3", events[0].Id);
        _mockDynamoDb.Verify(d => d.ScanAsync(It.IsAny<ScanRequest>(), default), Times.Exactly(2));
    }

    [Fact]
    public async Task GetEventAsync_ShouldMapDetailsMap()
    {
        var item = Item("evt-1", new DateTime(2026, 1, 1, 0, 0, 0, DateTimeKind.Utc));
        item["Details"] = new AttributeValue
        {
            M = new Dictionary<string, AttributeValue>
            {
                ["reason"] = new AttributeValue { S = "cleanup" },
                ["actor"] = new AttributeValue { S = "scheduler" },
            },
        };
        _mockDynamoDb
            .Setup(d => d.GetItemAsync(It.IsAny<GetItemRequest>(), default))
            .ReturnsAsync(new GetItemResponse { Item = item });

        var result = await _repository.GetEventAsync("evt-1");

        Assert.NotNull(result);
        Assert.Equal("cleanup", result!.Details!["reason"]);
        Assert.Equal("scheduler", result.Details["actor"]);
    }

    [Fact]
    public async Task DeleteEventsAsync_ShouldRetryUnprocessedItems_AndCountThemAsDeleted()
    {
        var unprocessed = new Dictionary<string, List<WriteRequest>>
        {
            ["test-audit-events"] = new List<WriteRequest> { DeleteRequestFor("evt-2") },
        };

        _mockDynamoDb
            .SetupSequence(d => d.BatchWriteItemAsync(It.IsAny<BatchWriteItemRequest>(), default))
            .ReturnsAsync(new BatchWriteItemResponse { UnprocessedItems = unprocessed })
            .ReturnsAsync(new BatchWriteItemResponse
            {
                UnprocessedItems = new Dictionary<string, List<WriteRequest>>(),
            });

        var deleted = await _repository.DeleteEventsAsync(new[] { "evt-1", "evt-2" });

        Assert.Equal(2, deleted);
        _mockDynamoDb.Verify(d => d.BatchWriteItemAsync(It.IsAny<BatchWriteItemRequest>(), default), Times.Exactly(2));
        _mockDynamoDb.Verify(
            d => d.BatchWriteItemAsync(It.Is<BatchWriteItemRequest>(r => r.RequestItems == unprocessed), default),
            Times.Once);
    }

    [Fact]
    public async Task DeleteEventsAsync_ShouldReportFailures_WhenRetriesAreExhausted()
    {
        var unprocessed = new Dictionary<string, List<WriteRequest>>
        {
            ["test-audit-events"] = new List<WriteRequest> { DeleteRequestFor("evt-1"), DeleteRequestFor("evt-2") },
        };
        _mockDynamoDb
            .Setup(d => d.BatchWriteItemAsync(It.IsAny<BatchWriteItemRequest>(), default))
            .ReturnsAsync(new BatchWriteItemResponse { UnprocessedItems = unprocessed });

        var deleted = await _repository.DeleteEventsAsync(new[] { "evt-1", "evt-2", "evt-3" });

        Assert.Equal(1, deleted);
        _mockDynamoDb.Verify(d => d.BatchWriteItemAsync(It.IsAny<BatchWriteItemRequest>(), default), Times.Exactly(6));
        _mockLogger.Verify(
            l => l.Log(
                LogLevel.Error,
                It.IsAny<EventId>(),
                It.IsAny<It.IsAnyType>(),
                It.IsAny<Exception>(),
                It.IsAny<Func<It.IsAnyType, Exception?, string>>()),
            Times.Once);
    }

    private void SetupTwoPageScan()
    {
        _mockDynamoDb
            .SetupSequence(d => d.ScanAsync(It.IsAny<ScanRequest>(), default))
            .ReturnsAsync(new ScanResponse
            {
                Items = new List<Dictionary<string, AttributeValue>>
                {
                    Item("evt-1", new DateTime(2026, 1, 1, 0, 0, 0, DateTimeKind.Utc)),
                    Item("evt-2", new DateTime(2026, 1, 2, 0, 0, 0, DateTimeKind.Utc)),
                },
                LastEvaluatedKey = new Dictionary<string, AttributeValue> { ["id"] = new AttributeValue { S = "evt-2" } },
            })
            .ReturnsAsync(new ScanResponse
            {
                Items = new List<Dictionary<string, AttributeValue>>
                {
                    Item("evt-3", new DateTime(2026, 1, 3, 0, 0, 0, DateTimeKind.Utc)),
                },
            });
    }

    private static WriteRequest DeleteRequestFor(string id) => new()
    {
        DeleteRequest = new DeleteRequest
        {
            Key = new Dictionary<string, AttributeValue> { ["id"] = new AttributeValue { S = id } },
        },
    };

    private static Dictionary<string, AttributeValue> Item(string id, DateTime timestamp) => new()
    {
        ["Id"] = new AttributeValue { S = id },
        ["UserId"] = new AttributeValue { S = "user-1" },
        ["Action"] = new AttributeValue { S = "read" },
        ["ResourceType"] = new AttributeValue { S = "file" },
        ["ResourceId"] = new AttributeValue { S = "resource-1" },
        ["Timestamp"] = new AttributeValue { S = timestamp.ToString("O") },
    };
}
