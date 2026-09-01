using Amazon.DynamoDBv2;
using Amazon.DynamoDBv2.Model;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Moq;
using OtterWorks.AuditService.Config;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

/// <summary>
/// Covers the scan-paging, timestamp-filter, batch-retry and attribute-mapping paths of
/// <see cref="DynamoDbAuditRepository"/>.
/// </summary>
public class DynamoDbAuditRepositoryScanTests
{
    private readonly Mock<IAmazonDynamoDB> _mockDynamoDb;
    private readonly DynamoDbAuditRepository _repository;

    public DynamoDbAuditRepositoryScanTests()
    {
        _mockDynamoDb = new Mock<IAmazonDynamoDB>();
        _repository = new DynamoDbAuditRepository(
            _mockDynamoDb.Object,
            Options.Create(new AwsSettings { DynamoDbTable = "test-audit-events", Region = "us-east-1" }),
            new Mock<ILogger<DynamoDbAuditRepository>>().Object);
    }

    [Fact]
    public async Task QueryEventsAsync_WithDateRange_ShouldBuildTimestampFilter()
    {
        var from = new DateTime(2026, 1, 1, 0, 0, 0, DateTimeKind.Utc);
        var to = new DateTime(2026, 2, 1, 0, 0, 0, DateTimeKind.Utc);
        StubSinglePageScan();

        await _repository.QueryEventsAsync(null, null, null, null, from, to, 1, 20);

        _mockDynamoDb.Verify(d => d.ScanAsync(It.Is<ScanRequest>(req =>
            req.FilterExpression == "#ts >= :fromTs AND #ts <= :toTs" &&
            req.ExpressionAttributeNames["#ts"] == "Timestamp" &&
            req.ExpressionAttributeValues[":fromTs"].S == from.ToString("O") &&
            req.ExpressionAttributeValues[":toTs"].S == to.ToString("O")),
            default), Times.Once);
    }

    [Fact]
    public async Task QueryEventsAsync_WithUpperBoundOnly_ShouldStillAliasTimestampAttribute()
    {
        var to = new DateTime(2026, 2, 1, 0, 0, 0, DateTimeKind.Utc);
        StubSinglePageScan();

        await _repository.QueryEventsAsync(null, null, null, null, null, to, 1, 20);

        _mockDynamoDb.Verify(d => d.ScanAsync(It.Is<ScanRequest>(req =>
            req.FilterExpression == "#ts <= :toTs" &&
            req.ExpressionAttributeNames["#ts"] == "Timestamp" &&
            !req.ExpressionAttributeValues.ContainsKey(":fromTs")),
            default), Times.Once);
    }

    [Fact]
    public async Task QueryEventsAsync_WithoutFilters_ShouldScanWholeTable()
    {
        StubSinglePageScan();

        await _repository.QueryEventsAsync(null, null, null, null, null, null, 1, 20);

        _mockDynamoDb.Verify(d => d.ScanAsync(It.Is<ScanRequest>(req =>
            req.TableName == "test-audit-events" &&
            req.FilterExpression == null &&
            req.ExpressionAttributeValues.Count == 0),
            default), Times.Once);
    }

    [Fact]
    public async Task QueryEventsAsync_WhenScanIsPaged_ShouldFollowLastEvaluatedKey()
    {
        var startKeys = StubTwoPageScan();

        var result = await _repository.QueryEventsAsync(null, null, null, null, null, null, 1, 20);

        Assert.Equal(2, result.Total);
        Assert.Equal(2, _mockDynamoDb.Invocations.Count(i => i.Method.Name == nameof(IAmazonDynamoDB.ScanAsync)));
        Assert.Empty(startKeys[0]!);
        Assert.Equal("page-2", startKeys[1]!["id"].S);
    }

    [Fact]
    public async Task QueryEventsAsync_ShouldReturnNewestFirstAcrossPages()
    {
        var older = DateTime.UtcNow.AddHours(-2);
        var newer = DateTime.UtcNow;
        StubTwoPageScan(
            firstPage: CreateItem("e-old", timestamp: older),
            secondPage: CreateItem("e-new", timestamp: newer));

        var result = await _repository.QueryEventsAsync(null, null, null, null, null, null, 1, 20);

        Assert.Equal(new[] { "e-new", "e-old" }, result.Events.Select(e => e.Id));
    }

    [Fact]
    public async Task GetAllUserEventsAsync_WhenScanIsPaged_ShouldReturnEveryPage()
    {
        StubTwoPageScan();

        var events = await _repository.GetAllUserEventsAsync("user-1");

        Assert.Equal(2, events.Count);
    }

    [Fact]
    public async Task GetResourceHistoryAsync_WhenScanIsPaged_ShouldReturnEveryPage()
    {
        StubTwoPageScan();

        var events = await _repository.GetResourceHistoryAsync("doc-1");

        Assert.Equal(2, events.Count);
    }

    [Fact]
    public async Task GetEventsByDateRangeAsync_WhenScanIsPaged_ShouldReturnEveryPage()
    {
        StubTwoPageScan();

        var events = await _repository.GetEventsByDateRangeAsync(DateTime.UtcNow.AddDays(-1), DateTime.UtcNow);

        Assert.Equal(2, events.Count);
    }

    [Fact]
    public async Task GetEventAsync_ShouldMapDetailsMapAndLowercaseIdFallback()
    {
        var item = new Dictionary<string, AttributeValue>
        {
            ["id"] = new AttributeValue { S = "evt-lower" },
            ["UserId"] = new AttributeValue { S = "user-1" },
            ["Timestamp"] = new AttributeValue { S = "not-a-timestamp" },
            ["Details"] = new AttributeValue
            {
                M = new Dictionary<string, AttributeValue> { ["reason"] = new AttributeValue { S = "cleanup" } },
            },
        };

        _mockDynamoDb
            .Setup(d => d.GetItemAsync(It.IsAny<GetItemRequest>(), default))
            .ReturnsAsync(new GetItemResponse { Item = item });

        var result = await _repository.GetEventAsync("evt-lower");

        Assert.NotNull(result);
        Assert.Equal("evt-lower", result.Id);
        Assert.Equal(DateTime.MinValue, result.Timestamp);
        Assert.Equal("cleanup", result.Details!["reason"]);
        Assert.Null(result.IpAddress);
    }

    [Fact]
    public async Task DeleteEventsAsync_WhenItemsAreUnprocessed_ShouldRetryAndReportFullDeletion()
    {
        var unprocessed = CreateUnprocessedItems("evt-1");

        _mockDynamoDb
            .SetupSequence(d => d.BatchWriteItemAsync(It.IsAny<BatchWriteItemRequest>(), default))
            .ReturnsAsync(new BatchWriteItemResponse { UnprocessedItems = unprocessed })
            .ReturnsAsync(new BatchWriteItemResponse());

        var deleted = await _repository.DeleteEventsAsync(new[] { "evt-1" });

        Assert.Equal(1, deleted);
        _mockDynamoDb.Verify(
            d => d.BatchWriteItemAsync(It.IsAny<BatchWriteItemRequest>(), default),
            Times.Exactly(2));
    }

    [Fact]
    public async Task DeleteEventsAsync_WhenRetriesAreExhausted_ShouldExcludeFailedItemsFromCount()
    {
        _mockDynamoDb
            .Setup(d => d.BatchWriteItemAsync(It.IsAny<BatchWriteItemRequest>(), default))
            .ReturnsAsync(() => new BatchWriteItemResponse { UnprocessedItems = CreateUnprocessedItems("evt-1") });

        var deleted = await _repository.DeleteEventsAsync(new[] { "evt-1", "evt-2" });

        Assert.Equal(1, deleted);
        _mockDynamoDb.Verify(
            d => d.BatchWriteItemAsync(It.IsAny<BatchWriteItemRequest>(), default),
            Times.Exactly(6));
    }

    [Fact]
    public async Task DeleteEventsAsync_WithNoIds_ShouldNotCallDynamoDb()
    {
        var deleted = await _repository.DeleteEventsAsync(Array.Empty<string>());

        Assert.Equal(0, deleted);
        _mockDynamoDb.Verify(
            d => d.BatchWriteItemAsync(It.IsAny<BatchWriteItemRequest>(), default),
            Times.Never);
    }

    private void StubSinglePageScan() =>
        _mockDynamoDb
            .Setup(d => d.ScanAsync(It.IsAny<ScanRequest>(), default))
            .ReturnsAsync(new ScanResponse
            {
                Items = new List<Dictionary<string, AttributeValue>>(),
                LastEvaluatedKey = new Dictionary<string, AttributeValue>(),
            });

    /// <summary>
    /// Stubs a scan that returns one item per page and snapshots the ExclusiveStartKey used for
    /// each call, so paging can be asserted independently of how the request object is reused.
    /// </summary>
    private List<Dictionary<string, AttributeValue>?> StubTwoPageScan(
        Dictionary<string, AttributeValue>? firstPage = null,
        Dictionary<string, AttributeValue>? secondPage = null)
    {
        var startKeys = new List<Dictionary<string, AttributeValue>?>();
        var call = 0;

        _mockDynamoDb
            .Setup(d => d.ScanAsync(It.IsAny<ScanRequest>(), default))
            .Callback<ScanRequest, CancellationToken>((req, _) => startKeys.Add(
                req.ExclusiveStartKey is null ? null : new Dictionary<string, AttributeValue>(req.ExclusiveStartKey)))
            .ReturnsAsync(() =>
            {
                call++;
                return call == 1
                    ? new ScanResponse
                    {
                        Items = new List<Dictionary<string, AttributeValue>> { firstPage ?? CreateItem("e1") },
                        LastEvaluatedKey = new Dictionary<string, AttributeValue>
                        {
                            ["id"] = new AttributeValue { S = "page-2" },
                        },
                    }
                    : new ScanResponse
                    {
                        Items = new List<Dictionary<string, AttributeValue>> { secondPage ?? CreateItem("e2") },
                        LastEvaluatedKey = new Dictionary<string, AttributeValue>(),
                    };
            });

        return startKeys;
    }

    private static Dictionary<string, AttributeValue> CreateItem(string id, DateTime? timestamp = null) =>
        new()
        {
            ["Id"] = new AttributeValue { S = id },
            ["UserId"] = new AttributeValue { S = "user-1" },
            ["Action"] = new AttributeValue { S = "create" },
            ["ResourceType"] = new AttributeValue { S = "document" },
            ["ResourceId"] = new AttributeValue { S = "doc-1" },
            ["Timestamp"] = new AttributeValue { S = (timestamp ?? DateTime.UtcNow).ToString("O") },
        };

    private static Dictionary<string, List<WriteRequest>> CreateUnprocessedItems(string id) =>
        new()
        {
            ["test-audit-events"] = new List<WriteRequest>
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
}
