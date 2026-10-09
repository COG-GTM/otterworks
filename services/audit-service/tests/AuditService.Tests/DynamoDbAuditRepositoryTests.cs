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
    public async Task QueryEventsAsync_ShouldReturnPaginatedResults()
    {
        var items = new List<Dictionary<string, AttributeValue>>
        {
            CreateDynamoDbItem("e1", "user-1", "create", "document", "doc-1"),
            CreateDynamoDbItem("e2", "user-1", "update", "document", "doc-2"),
            CreateDynamoDbItem("e3", "user-1", "delete", "document", "doc-3"),
        };

        _mockDynamoDb
            .Setup(d => d.ScanAsync(It.IsAny<ScanRequest>(), default))
            .ReturnsAsync(new ScanResponse
            {
                Items = items,
                LastEvaluatedKey = new Dictionary<string, AttributeValue>(),
            });

        var result = await _repository.QueryEventsAsync("user-1", null, null, null, null, null, 1, 2);

        Assert.Equal(3, result.Total);
        Assert.Equal(2, result.Events.Count);
        Assert.Equal(1, result.Page);
        Assert.Equal(2, result.PageSize);
    }

    [Fact]
    public async Task QueryEventsAsync_WithFilters_ShouldApplyFilterExpression()
    {
        _mockDynamoDb
            .Setup(d => d.ScanAsync(It.IsAny<ScanRequest>(), default))
            .ReturnsAsync(new ScanResponse
            {
                Items = new List<Dictionary<string, AttributeValue>>(),
                LastEvaluatedKey = new Dictionary<string, AttributeValue>(),
            });

        await _repository.QueryEventsAsync("user-1", "create", "document", "doc-1", null, null, 1, 20);

        _mockDynamoDb.Verify(d => d.ScanAsync(It.Is<ScanRequest>(req =>
            req.FilterExpression != null &&
            req.FilterExpression.Contains("#uid = :uid") &&
            req.FilterExpression.Contains("#act = :act") &&
            req.FilterExpression.Contains("ResourceType = :rt") &&
            req.FilterExpression.Contains("ResourceId = :rid")),
            default), Times.Once);
    }

    [Fact]
    public async Task GetAllUserEventsAsync_ShouldFilterByUserId()
    {
        var items = new List<Dictionary<string, AttributeValue>>
        {
            CreateDynamoDbItem("e1", "user-1", "create", "document", "doc-1"),
        };

        _mockDynamoDb
            .Setup(d => d.ScanAsync(It.IsAny<ScanRequest>(), default))
            .ReturnsAsync(new ScanResponse
            {
                Items = items,
                LastEvaluatedKey = new Dictionary<string, AttributeValue>(),
            });

        var result = await _repository.GetAllUserEventsAsync("user-1");

        Assert.Single(result);
        Assert.Equal("user-1", result[0].UserId);
    }

    [Fact]
    public async Task GetResourceHistoryAsync_ShouldFilterByResourceId()
    {
        var items = new List<Dictionary<string, AttributeValue>>
        {
            CreateDynamoDbItem("e1", "user-1", "create", "document", "doc-1"),
            CreateDynamoDbItem("e2", "user-2", "update", "document", "doc-1"),
        };

        _mockDynamoDb
            .Setup(d => d.ScanAsync(It.IsAny<ScanRequest>(), default))
            .ReturnsAsync(new ScanResponse
            {
                Items = items,
                LastEvaluatedKey = new Dictionary<string, AttributeValue>(),
            });

        var result = await _repository.GetResourceHistoryAsync("doc-1");

        Assert.Equal(2, result.Count);

        _mockDynamoDb.Verify(d => d.ScanAsync(It.Is<ScanRequest>(req =>
            req.FilterExpression == "(ResourceId = :rid) AND attribute_not_exists(#tid)" &&
            req.ExpressionAttributeValues[":rid"].S == "doc-1"),
            default), Times.Once);
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
    public async Task GetEventsByDateRangeAsync_ShouldFilterByTimestamp()
    {
        var from = DateTime.UtcNow.AddDays(-7);
        var to = DateTime.UtcNow;

        _mockDynamoDb
            .Setup(d => d.ScanAsync(It.IsAny<ScanRequest>(), default))
            .ReturnsAsync(new ScanResponse
            {
                Items = new List<Dictionary<string, AttributeValue>>(),
                LastEvaluatedKey = new Dictionary<string, AttributeValue>(),
            });

        await _repository.GetEventsByDateRangeAsync(from, to);

        _mockDynamoDb.Verify(d => d.ScanAsync(It.Is<ScanRequest>(req =>
            req.FilterExpression == "(#ts >= :fromTs AND #ts <= :toTs) AND attribute_not_exists(#tid)" &&
            req.ExpressionAttributeNames["#ts"] == "Timestamp"),
            default), Times.Once);
    }

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

    private DynamoDbAuditRepository RepositoryForTenant(string? tenantId) =>
        new(_mockDynamoDb.Object, Options.Create(new AwsSettings
        {
            DynamoDbTable = "test-audit-events",
            Region = "us-east-1",
            TenantId = tenantId,
        }), _mockLogger.Object);

    [Fact]
    public async Task SaveEventAsync_WithTenantConfigured_ShouldStampTenantId()
    {
        _mockDynamoDb
            .Setup(d => d.PutItemAsync(It.IsAny<PutItemRequest>(), default))
            .ReturnsAsync(new PutItemResponse());

        await RepositoryForTenant("tenant-a").SaveEventAsync(new AuditEvent
        {
            Id = "e1", UserId = "u1", Action = "create", ResourceType = "doc", ResourceId = "d1", Timestamp = DateTime.UtcNow,
        });

        _mockDynamoDb.Verify(d => d.PutItemAsync(It.Is<PutItemRequest>(req =>
            req.Item["TenantId"].S == "tenant-a"),
            default), Times.Once);
    }

    [Fact]
    public async Task GetArchivableEventsAsync_WithTenantConfigured_ShouldFilterByTenant()
    {
        var cutoff = DateTime.UtcNow.AddDays(-90);
        _mockDynamoDb
            .Setup(d => d.ScanAsync(It.IsAny<ScanRequest>(), default))
            .ReturnsAsync(new ScanResponse { Items = new List<Dictionary<string, AttributeValue>>() });

        await RepositoryForTenant("tenant-a").GetArchivableEventsAsync(cutoff);

        _mockDynamoDb.Verify(d => d.ScanAsync(It.Is<ScanRequest>(req =>
            req.FilterExpression == "(#ts <= :toTs) AND #tid = :tid" &&
            req.ExpressionAttributeNames["#tid"] == "TenantId" &&
            req.ExpressionAttributeValues[":tid"].S == "tenant-a" &&
            req.ExpressionAttributeValues[":toTs"].S == cutoff.ToString("O")),
            default), Times.Once);
    }

    [Fact]
    public async Task GetArchivableEventsAsync_WithoutTenant_ShouldOnlyMatchUntaggedEvents()
    {
        _mockDynamoDb
            .Setup(d => d.ScanAsync(It.IsAny<ScanRequest>(), default))
            .ReturnsAsync(new ScanResponse { Items = new List<Dictionary<string, AttributeValue>>() });

        await _repository.GetArchivableEventsAsync(DateTime.UtcNow);

        _mockDynamoDb.Verify(d => d.ScanAsync(It.Is<ScanRequest>(req =>
            req.FilterExpression.Contains("attribute_not_exists(#tid)") &&
            !req.ExpressionAttributeValues.ContainsKey(":tid")),
            default), Times.Once);
    }

    [Fact]
    public async Task QueryEventsAsync_WithTenantConfigured_ShouldOnlyReturnTenantEvents()
    {
        _mockDynamoDb
            .Setup(d => d.ScanAsync(It.IsAny<ScanRequest>(), default))
            .ReturnsAsync(new ScanResponse { Items = new List<Dictionary<string, AttributeValue>>() });

        await RepositoryForTenant("tenant-a").QueryEventsAsync(null, null, null, null, null, null, 1, 10);
        await RepositoryForTenant("tenant-a").GetAllUserEventsAsync("u1");

        _mockDynamoDb.Verify(d => d.ScanAsync(It.Is<ScanRequest>(req =>
            req.FilterExpression.EndsWith("#tid = :tid") &&
            req.ExpressionAttributeNames["#tid"] == "TenantId" &&
            req.ExpressionAttributeValues[":tid"].S == "tenant-a"),
            default), Times.Exactly(2));
    }

    [Theory]
    [InlineData("tenant-b", false)]
    [InlineData(null, false)]
    [InlineData("tenant-a", true)]
    public async Task GetEventAsync_WithTenantConfigured_ShouldHideOtherTenantsEvents(string? itemTenant, bool visible)
    {
        var item = new Dictionary<string, AttributeValue>
        {
            ["id"] = new AttributeValue { S = "e1" },
            ["UserId"] = new AttributeValue { S = "u1" },
            ["Action"] = new AttributeValue { S = "create" },
            ["ResourceType"] = new AttributeValue { S = "doc" },
            ["ResourceId"] = new AttributeValue { S = "d1" },
            ["Timestamp"] = new AttributeValue { S = DateTime.UtcNow.ToString("O") },
        };
        if (itemTenant is not null)
            item["TenantId"] = new AttributeValue { S = itemTenant };
        _mockDynamoDb
            .Setup(d => d.GetItemAsync(It.IsAny<GetItemRequest>(), default))
            .ReturnsAsync(new GetItemResponse { Item = item });

        var result = await RepositoryForTenant("tenant-a").GetEventAsync("e1");

        Assert.Equal(visible, result is not null);
    }
}
