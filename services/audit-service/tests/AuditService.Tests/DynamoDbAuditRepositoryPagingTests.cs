using System.Runtime.CompilerServices;
using Amazon.DynamoDBv2;
using Amazon.DynamoDBv2.Model;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Moq;
using OtterWorks.AuditService.Config;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

/// <summary>
/// Covers the repository paths the original suite left untouched: date filters, DynamoDB
/// pagination, unprocessed batch-delete retries, and attribute mapping fallbacks.
/// </summary>
public class DynamoDbAuditRepositoryPagingTests
{
    private const string TableName = "test-audit-events";

    private readonly Mock<IAmazonDynamoDB> _dynamoDb = new();
    private readonly Mock<ILogger<DynamoDbAuditRepository>> _logger = new();
    private readonly DynamoDbAuditRepository _repository;

    public DynamoDbAuditRepositoryPagingTests()
    {
        _repository = new DynamoDbAuditRepository(
            _dynamoDb.Object,
            Options.Create(new AwsSettings { DynamoDbTable = TableName }),
            _logger.Object);
    }

    [Fact]
    public async Task QueryEventsAsync_FiltersOnBothEndsOfTheDateRange()
    {
        var from = new DateTime(2026, 1, 1, 0, 0, 0, DateTimeKind.Utc);
        var to = new DateTime(2026, 1, 31, 0, 0, 0, DateTimeKind.Utc);
        var request = CaptureScan();

        await _repository.QueryEventsAsync(null, null, null, null, from, to, 1, 20);

        Assert.Equal("#ts >= :fromTs AND #ts <= :toTs", request.Value!.FilterExpression);
        Assert.Equal("Timestamp", request.Value.ExpressionAttributeNames["#ts"]);
        Assert.Equal(from.ToString("O"), request.Value.ExpressionAttributeValues[":fromTs"].S);
        Assert.Equal(to.ToString("O"), request.Value.ExpressionAttributeValues[":toTs"].S);
    }

    [Fact]
    public async Task QueryEventsAsync_RegistersTimestampAlias_WhenOnlyUpperBoundIsGiven()
    {
        var to = new DateTime(2026, 1, 31, 0, 0, 0, DateTimeKind.Utc);
        var request = CaptureScan();

        await _repository.QueryEventsAsync(null, null, null, null, null, to, 1, 20);

        Assert.Equal("#ts <= :toTs", request.Value!.FilterExpression);
        Assert.Equal("Timestamp", request.Value.ExpressionAttributeNames["#ts"]);
        Assert.DoesNotContain(":fromTs", request.Value.ExpressionAttributeValues.Keys);
    }

    [Fact]
    public async Task QueryEventsAsync_FollowsPaginationAndSortsNewestFirst()
    {
        SetupPagedScan(
            Item("evt-old", new DateTime(2026, 1, 1, 0, 0, 0, DateTimeKind.Utc)),
            Item("evt-new", new DateTime(2026, 6, 1, 0, 0, 0, DateTimeKind.Utc)));

        var page = await _repository.QueryEventsAsync(null, null, null, null, null, null, 1, 20);

        Assert.Equal(2, page.Total);
        Assert.Equal(new[] { "evt-new", "evt-old" }, page.Events.Select(e => e.Id));
        _dynamoDb.Verify(d => d.ScanAsync(It.IsAny<ScanRequest>(), It.IsAny<CancellationToken>()), Times.Exactly(2));
    }

    [Fact]
    public async Task GetAllUserEventsAsync_FollowsPagination()
    {
        SetupPagedScan(Item("evt-1"), Item("evt-2"));

        var events = await _repository.GetAllUserEventsAsync("user-1");

        Assert.Equal(2, events.Count);
        _dynamoDb.Verify(d => d.ScanAsync(It.IsAny<ScanRequest>(), It.IsAny<CancellationToken>()), Times.Exactly(2));
    }

    [Fact]
    public async Task GetResourceHistoryAsync_FollowsPagination()
    {
        SetupPagedScan(Item("evt-1"), Item("evt-2"));

        var events = await _repository.GetResourceHistoryAsync("file-1");

        Assert.Equal(2, events.Count);
        _dynamoDb.Verify(d => d.ScanAsync(It.IsAny<ScanRequest>(), It.IsAny<CancellationToken>()), Times.Exactly(2));
    }

    [Fact]
    public async Task GetEventsByDateRangeAsync_FollowsPagination()
    {
        SetupPagedScan(Item("evt-1"), Item("evt-2"));

        var events = await _repository.GetEventsByDateRangeAsync(DateTime.MinValue, DateTime.UtcNow);

        Assert.Equal(2, events.Count);
        _dynamoDb.Verify(d => d.ScanAsync(It.IsAny<ScanRequest>(), It.IsAny<CancellationToken>()), Times.Exactly(2));
    }

    [Fact]
    public async Task DeleteEventsAsync_RetriesUnprocessedItemsUntilTheyClear()
    {
        _dynamoDb
            .SetupSequence(d => d.BatchWriteItemAsync(It.IsAny<BatchWriteItemRequest>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(new BatchWriteItemResponse { UnprocessedItems = Unprocessed("evt-2") })
            .ReturnsAsync(new BatchWriteItemResponse());

        var deleted = await _repository.DeleteEventsAsync(new[] { "evt-1", "evt-2" });

        Assert.Equal(2, deleted);
        _dynamoDb.Verify(
            d => d.BatchWriteItemAsync(It.IsAny<BatchWriteItemRequest>(), It.IsAny<CancellationToken>()),
            Times.Exactly(2));
        VerifyLogged(LogLevel.Warning, "Retrying 1 unprocessed delete items");
    }

    [Fact]
    public async Task DeleteEventsAsync_ReportsFailures_WhenRetriesAreExhausted()
    {
        _dynamoDb
            .Setup(d => d.BatchWriteItemAsync(It.IsAny<BatchWriteItemRequest>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(new BatchWriteItemResponse { UnprocessedItems = Unprocessed("evt-2") });

        var deleted = await _repository.DeleteEventsAsync(new[] { "evt-1", "evt-2" });

        Assert.Equal(1, deleted);
        _dynamoDb.Verify(
            d => d.BatchWriteItemAsync(It.IsAny<BatchWriteItemRequest>(), It.IsAny<CancellationToken>()),
            Times.Exactly(6));
        VerifyLogged(LogLevel.Error, "Failed to delete 1 items after retries");
    }

    [Fact]
    public async Task DeleteEventsAsync_SplitsIdsIntoBatchesOfTwentyFive()
    {
        var requests = new List<BatchWriteItemRequest>();
        _dynamoDb
            .Setup(d => d.BatchWriteItemAsync(It.IsAny<BatchWriteItemRequest>(), It.IsAny<CancellationToken>()))
            .Callback<BatchWriteItemRequest, CancellationToken>((r, _) => requests.Add(r))
            .ReturnsAsync(new BatchWriteItemResponse());

        var deleted = await _repository.DeleteEventsAsync(Enumerable.Range(1, 30).Select(i => $"evt-{i}"));

        Assert.Equal(30, deleted);
        Assert.Equal(new[] { 25, 5 }, requests.Select(r => r.RequestItems[TableName].Count));
    }

    [Fact]
    public async Task GetEventAsync_MapsDetailsAndLowercaseIdFallback()
    {
        var item = new Dictionary<string, AttributeValue>
        {
            ["id"] = new AttributeValue { S = "evt-lower" },
            ["UserId"] = new AttributeValue { S = "user-1" },
            ["Timestamp"] = new AttributeValue { S = "not-a-date" },
            ["Details"] = new AttributeValue
            {
                M = new Dictionary<string, AttributeValue> { ["reason"] = new AttributeValue { S = "cleanup" } },
            },
        };
        _dynamoDb
            .Setup(d => d.GetItemAsync(It.IsAny<GetItemRequest>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(new GetItemResponse { Item = item });

        var result = await _repository.GetEventAsync("evt-lower");

        Assert.NotNull(result);
        Assert.Equal("evt-lower", result!.Id);
        Assert.Equal(DateTime.MinValue, result.Timestamp);
        Assert.Equal(string.Empty, result.Action);
        Assert.Null(result.IpAddress);
        Assert.Equal("cleanup", result.Details!["reason"]);
    }

    private StrongBox<ScanRequest> CaptureScan()
    {
        var box = new StrongBox<ScanRequest>();
        _dynamoDb
            .Setup(d => d.ScanAsync(It.IsAny<ScanRequest>(), It.IsAny<CancellationToken>()))
            .Callback<ScanRequest, CancellationToken>((r, _) => box.Value = r)
            .ReturnsAsync(new ScanResponse());
        return box;
    }

    private void SetupPagedScan(
        Dictionary<string, AttributeValue> firstPageItem,
        Dictionary<string, AttributeValue> secondPageItem)
    {
        var lastKey = new Dictionary<string, AttributeValue> { ["id"] = new AttributeValue { S = "cursor" } };
        _dynamoDb
            .SetupSequence(d => d.ScanAsync(It.IsAny<ScanRequest>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(new ScanResponse
            {
                Items = new List<Dictionary<string, AttributeValue>> { firstPageItem },
                LastEvaluatedKey = lastKey,
            })
            .ReturnsAsync(new ScanResponse
            {
                Items = new List<Dictionary<string, AttributeValue>> { secondPageItem },
            });
    }

    private static Dictionary<string, AttributeValue> Item(string id, DateTime? timestamp = null) => new()
    {
        ["Id"] = new AttributeValue { S = id },
        ["UserId"] = new AttributeValue { S = "user-1" },
        ["Action"] = new AttributeValue { S = "read" },
        ["ResourceType"] = new AttributeValue { S = "file" },
        ["ResourceId"] = new AttributeValue { S = "file-1" },
        ["Timestamp"] = new AttributeValue { S = (timestamp ?? DateTime.UtcNow).ToString("O") },
    };

    private static Dictionary<string, List<WriteRequest>> Unprocessed(string id) => new()
    {
        [TableName] = new List<WriteRequest>
        {
            new()
            {
                DeleteRequest = new DeleteRequest
                {
                    Key = new Dictionary<string, AttributeValue> { ["id"] = new AttributeValue { S = id } },
                },
            },
        },
    };

    private void VerifyLogged(LogLevel level, string messageFragment) =>
        _logger.Verify(
            l => l.Log(
                level,
                It.IsAny<EventId>(),
                It.Is<It.IsAnyType>((state, _) => state.ToString()!.Contains(messageFragment)),
                It.IsAny<Exception?>(),
                It.IsAny<Func<It.IsAnyType, Exception?, string>>()),
            Times.AtLeastOnce);
}
