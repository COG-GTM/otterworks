using Amazon.DynamoDBv2;
using Amazon.DynamoDBv2.Model;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Moq;
using OtterWorks.AuditService.Config;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

public class DynamoDbAuditRepositoryPaginationTests
{
    private readonly Mock<IAmazonDynamoDB> _mockDynamoDb = new();
    private readonly Mock<ILogger<DynamoDbAuditRepository>> _mockLogger = new();
    private readonly List<int> _scanStartKeyCounts = new();
    private readonly DynamoDbAuditRepository _repository;

    public DynamoDbAuditRepositoryPaginationTests()
    {
        var options = Options.Create(new AwsSettings
        {
            DynamoDbTable = "test-audit-events",
            Region = "us-east-1",
        });

        _repository = new DynamoDbAuditRepository(_mockDynamoDb.Object, options, _mockLogger.Object);
    }

    [Fact]
    public async Task QueryEventsAsync_ShouldApplyTimestampFilters_WhenDateRangeIsGiven()
    {
        var from = new DateTime(2026, 1, 1, 0, 0, 0, DateTimeKind.Utc);
        var to = new DateTime(2026, 2, 1, 0, 0, 0, DateTimeKind.Utc);
        SetupScanPages(new ScanResponse { Items = new List<Dictionary<string, AttributeValue>>() });

        await _repository.QueryEventsAsync(null, null, null, null, from, to, 1, 20);

        _mockDynamoDb.Verify(d => d.ScanAsync(It.Is<ScanRequest>(req =>
            req.FilterExpression == "#ts >= :fromTs AND #ts <= :toTs" &&
            req.ExpressionAttributeNames["#ts"] == "Timestamp" &&
            req.ExpressionAttributeValues[":fromTs"].S == from.ToString("O") &&
            req.ExpressionAttributeValues[":toTs"].S == to.ToString("O")),
            default), Times.Once);
    }

    [Fact]
    public async Task QueryEventsAsync_ShouldAliasTimestamp_WhenOnlyTheUpperBoundIsGiven()
    {
        var to = new DateTime(2026, 2, 1, 0, 0, 0, DateTimeKind.Utc);
        SetupScanPages(new ScanResponse { Items = new List<Dictionary<string, AttributeValue>>() });

        await _repository.QueryEventsAsync(null, null, null, null, null, to, 1, 20);

        _mockDynamoDb.Verify(d => d.ScanAsync(It.Is<ScanRequest>(req =>
            req.FilterExpression == "#ts <= :toTs" &&
            req.ExpressionAttributeNames["#ts"] == "Timestamp"),
            default), Times.Once);
    }

    [Fact]
    public async Task QueryEventsAsync_ShouldFollowPagination_UntilLastEvaluatedKeyIsEmpty()
    {
        SetupScanPages(
            CreatePage("e1", lastEvaluatedKey: true),
            CreatePage("e2", lastEvaluatedKey: false));

        var result = await _repository.QueryEventsAsync(null, null, null, null, null, null, 1, 20);

        Assert.Equal(2, result.Total);
        Assert.Equal(new[] { 0, 1 }, _scanStartKeyCounts);
    }

    [Fact]
    public async Task GetAllUserEventsAsync_ShouldFollowPagination()
    {
        SetupScanPages(
            CreatePage("e1", lastEvaluatedKey: true),
            CreatePage("e2", lastEvaluatedKey: false));

        var result = await _repository.GetAllUserEventsAsync("user-1");

        Assert.Equal(2, result.Count);
        _mockDynamoDb.Verify(d => d.ScanAsync(It.IsAny<ScanRequest>(), default), Times.Exactly(2));
    }

    [Fact]
    public async Task GetResourceHistoryAsync_ShouldFollowPagination()
    {
        SetupScanPages(
            CreatePage("e1", lastEvaluatedKey: true),
            CreatePage("e2", lastEvaluatedKey: false));

        var result = await _repository.GetResourceHistoryAsync("doc-1");

        Assert.Equal(2, result.Count);
        _mockDynamoDb.Verify(d => d.ScanAsync(It.IsAny<ScanRequest>(), default), Times.Exactly(2));
    }

    [Fact]
    public async Task GetEventsByDateRangeAsync_ShouldFollowPagination()
    {
        SetupScanPages(
            CreatePage("e1", lastEvaluatedKey: true),
            CreatePage("e2", lastEvaluatedKey: false));

        var result = await _repository.GetEventsByDateRangeAsync(DateTime.UtcNow.AddDays(-1), DateTime.UtcNow);

        Assert.Equal(2, result.Count);
        _mockDynamoDb.Verify(d => d.ScanAsync(It.IsAny<ScanRequest>(), default), Times.Exactly(2));
    }

    [Fact]
    public async Task GetEventsByDateRangeAsync_ShouldMapAllAttributes()
    {
        var timestamp = new DateTime(2026, 1, 15, 10, 0, 0, DateTimeKind.Utc);
        var item = new Dictionary<string, AttributeValue>
        {
            ["id"] = new AttributeValue { S = "lowercase-id" },
            ["UserId"] = new AttributeValue { S = "user-1" },
            ["Action"] = new AttributeValue { S = "share" },
            ["ResourceType"] = new AttributeValue { S = "file" },
            ["ResourceId"] = new AttributeValue { S = "file-1" },
            ["Timestamp"] = new AttributeValue { S = timestamp.ToString("O") },
            ["IpAddress"] = new AttributeValue { S = "10.0.0.1" },
            ["UserAgent"] = new AttributeValue { S = "TestAgent" },
            ["Details"] = new AttributeValue
            {
                M = new Dictionary<string, AttributeValue> { ["sharedWithUserId"] = new AttributeValue { S = "user-2" } },
            },
        };

        SetupScanPages(new ScanResponse
        {
            Items = new List<Dictionary<string, AttributeValue>> { item },
            LastEvaluatedKey = new Dictionary<string, AttributeValue>(),
        });

        var result = await _repository.GetEventsByDateRangeAsync(DateTime.UtcNow.AddDays(-1), DateTime.UtcNow);

        var mapped = Assert.Single(result);
        Assert.Equal("lowercase-id", mapped.Id);
        Assert.Equal(timestamp, mapped.Timestamp);
        Assert.Equal("10.0.0.1", mapped.IpAddress);
        Assert.Equal("TestAgent", mapped.UserAgent);
        Assert.Equal("user-2", mapped.Details!["sharedWithUserId"]);
    }

    [Fact]
    public async Task GetEventsByDateRangeAsync_ShouldFallBackToDefaults_ForUnmappableItems()
    {
        SetupScanPages(new ScanResponse
        {
            Items = new List<Dictionary<string, AttributeValue>> { new() },
            LastEvaluatedKey = new Dictionary<string, AttributeValue>(),
        });

        var result = await _repository.GetEventsByDateRangeAsync(DateTime.UtcNow.AddDays(-1), DateTime.UtcNow);

        var mapped = Assert.Single(result);
        Assert.Equal(string.Empty, mapped.Id);
        Assert.Equal(string.Empty, mapped.UserId);
        Assert.Equal(DateTime.MinValue, mapped.Timestamp);
        Assert.Null(mapped.IpAddress);
        Assert.Null(mapped.Details);
    }

    [Fact]
    public async Task DeleteEventsAsync_ShouldRetryUnprocessedItems()
    {
        var unprocessed = new Dictionary<string, List<WriteRequest>>
        {
            ["test-audit-events"] = new List<WriteRequest> { new() { DeleteRequest = new DeleteRequest() } },
        };

        _mockDynamoDb
            .SetupSequence(d => d.BatchWriteItemAsync(It.IsAny<BatchWriteItemRequest>(), default))
            .ReturnsAsync(new BatchWriteItemResponse { UnprocessedItems = unprocessed })
            .ReturnsAsync(new BatchWriteItemResponse());

        var deleted = await _repository.DeleteEventsAsync(new[] { "event-1" });

        Assert.Equal(1, deleted);
        _mockDynamoDb.Verify(d => d.BatchWriteItemAsync(It.IsAny<BatchWriteItemRequest>(), default), Times.Exactly(2));
    }

    /// <summary>
    /// Serves <paramref name="pages"/> in order and records the paging key of every scan.
    /// </summary>
    private void SetupScanPages(params ScanResponse[] pages)
    {
        var served = 0;
        _mockDynamoDb
            .Setup(d => d.ScanAsync(It.IsAny<ScanRequest>(), default))
            .Returns((ScanRequest request, CancellationToken _) =>
            {
                _scanStartKeyCounts.Add(request.ExclusiveStartKey?.Count ?? 0);
                return Task.FromResult(pages[Math.Min(served++, pages.Length - 1)]);
            });
    }

    private static ScanResponse CreatePage(string id, bool lastEvaluatedKey) => new()
    {
        Items = new List<Dictionary<string, AttributeValue>>
        {
            new()
            {
                ["Id"] = new AttributeValue { S = id },
                ["UserId"] = new AttributeValue { S = "user-1" },
                ["Timestamp"] = new AttributeValue { S = DateTime.UtcNow.ToString("O") },
            },
        },
        LastEvaluatedKey = lastEvaluatedKey
            ? new Dictionary<string, AttributeValue> { ["Id"] = new AttributeValue { S = id } }
            : new Dictionary<string, AttributeValue>(),
    };
}
