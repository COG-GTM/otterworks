using System.Runtime.CompilerServices;
using Amazon.DynamoDBv2;
using Amazon.DynamoDBv2.Model;
using Microsoft.Extensions.Options;
using OtterWorks.AuditService.Config;

namespace OtterWorks.AuditService.Services;

public class DynamoDbAuditRepository : IAuditRepository
{
    private readonly IAmazonDynamoDB _dynamoDb;
    private readonly AwsSettings _settings;
    private readonly AuditLimits _limits;
    private readonly ILogger<DynamoDbAuditRepository> _logger;

    public DynamoDbAuditRepository(
        IAmazonDynamoDB dynamoDb,
        IOptions<AwsSettings> settings,
        IOptions<AuditLimits> limits,
        ILogger<DynamoDbAuditRepository> logger)
    {
        _dynamoDb = dynamoDb;
        _settings = settings.Value;
        _limits = limits.Value;
        _logger = logger;
    }

    public async Task SaveEventAsync(AuditEvent auditEvent)
    {
        var item = new Dictionary<string, AttributeValue>
        {
            ["id"] = new AttributeValue { S = auditEvent.Id },
            ["Id"] = new AttributeValue { S = auditEvent.Id },
            ["UserId"] = new AttributeValue { S = auditEvent.UserId },
            ["Action"] = new AttributeValue { S = auditEvent.Action },
            ["ResourceType"] = new AttributeValue { S = auditEvent.ResourceType },
            ["ResourceId"] = new AttributeValue { S = auditEvent.ResourceId },
            ["Timestamp"] = new AttributeValue { S = auditEvent.Timestamp.ToString("O") },
        };

        if (auditEvent.IpAddress is not null)
            item["IpAddress"] = new AttributeValue { S = auditEvent.IpAddress };

        if (auditEvent.UserAgent is not null)
            item["UserAgent"] = new AttributeValue { S = auditEvent.UserAgent };

        if (auditEvent.Details is not null && auditEvent.Details.Count > 0)
        {
            item["Details"] = new AttributeValue
            {
                M = auditEvent.Details.ToDictionary(
                    kvp => kvp.Key,
                    kvp => new AttributeValue { S = kvp.Value })
            };
        }

        var request = new PutItemRequest
        {
            TableName = _settings.DynamoDbTable,
            Item = item,
        };

        await _dynamoDb.PutItemAsync(request);
        _logger.LogDebug("Saved audit event {Id} to DynamoDB table {Table}", auditEvent.Id, _settings.DynamoDbTable);
    }

    public async Task<AuditEvent?> GetEventAsync(string id)
    {
        var request = new GetItemRequest
        {
            TableName = _settings.DynamoDbTable,
            Key = new Dictionary<string, AttributeValue>
            {
                ["id"] = new AttributeValue { S = id },
            },
        };

        var response = await _dynamoDb.GetItemAsync(request);
        if (response.Item is null || response.Item.Count == 0)
            return null;

        return MapToAuditEvent(response.Item);
    }

    public async Task<AuditEventPage> QueryEventsAsync(
        string? userId, string? action, string? resourceType, string? resourceId,
        DateTime? from, DateTime? to, int page, int pageSize)
    {
        var filterExpressions = new List<string>();
        var expressionValues = new Dictionary<string, AttributeValue>();
        var expressionNames = new Dictionary<string, string>();

        if (!string.IsNullOrEmpty(userId))
        {
            filterExpressions.Add("#uid = :uid");
            expressionValues[":uid"] = new AttributeValue { S = userId };
            expressionNames["#uid"] = "UserId";
        }

        if (!string.IsNullOrEmpty(action))
        {
            filterExpressions.Add("#act = :act");
            expressionValues[":act"] = new AttributeValue { S = action };
            expressionNames["#act"] = "Action";
        }

        if (!string.IsNullOrEmpty(resourceType))
        {
            filterExpressions.Add("ResourceType = :rt");
            expressionValues[":rt"] = new AttributeValue { S = resourceType };
        }

        if (!string.IsNullOrEmpty(resourceId))
        {
            filterExpressions.Add("ResourceId = :rid");
            expressionValues[":rid"] = new AttributeValue { S = resourceId };
        }

        if (from.HasValue)
        {
            filterExpressions.Add("#ts >= :fromTs");
            expressionValues[":fromTs"] = new AttributeValue { S = from.Value.ToString("O") };
            expressionNames["#ts"] = "Timestamp";
        }

        if (to.HasValue)
        {
            expressionNames["#ts"] = "Timestamp";
            filterExpressions.Add("#ts <= :toTs");
            expressionValues[":toTs"] = new AttributeValue { S = to.Value.ToString("O") };
        }

        var scanRequest = new ScanRequest
        {
            TableName = _settings.DynamoDbTable,
        };

        if (filterExpressions.Count > 0)
        {
            scanRequest.FilterExpression = string.Join(" AND ", filterExpressions);
            scanRequest.ExpressionAttributeValues = expressionValues;
        }

        scanRequest.ExpressionAttributeNames = expressionNames;

        var window = Math.Min(Math.Max(page, 1) * (long)pageSize, _limits.MaxQueryWindow);
        var (keys, total) = await ScanNewestKeysAsync(scanRequest, (int)window);
        var pageKeys = keys.Skip((Math.Max(page, 1) - 1) * pageSize).Take(pageSize).ToList();
        var paged = await BatchGetEventsAsync(pageKeys);

        _logger.LogDebug("Queried audit events: userId={UserId}, action={Action}, total={Total}", userId, action, total);
        return new AuditEventPage
        {
            Events = paged,
            Total = total,
            Page = page,
            PageSize = pageSize,
        };
    }

    public IAsyncEnumerable<AuditEvent> StreamUserEventsAsync(
        string userId, DateTime from, DateTime to, CancellationToken cancellationToken = default)
    {
        var scanRequest = new ScanRequest
        {
            TableName = _settings.DynamoDbTable,
            FilterExpression = "#uid = :uid AND #ts >= :fromTs AND #ts <= :toTs",
            ExpressionAttributeNames = new Dictionary<string, string>
            {
                ["#uid"] = "UserId",
                ["#ts"] = "Timestamp",
            },
            ExpressionAttributeValues = new Dictionary<string, AttributeValue>
            {
                [":uid"] = new AttributeValue { S = userId },
                [":fromTs"] = new AttributeValue { S = from.ToString("O") },
                [":toTs"] = new AttributeValue { S = to.ToString("O") },
            },
        };

        return StreamScanAsync(scanRequest, cancellationToken);
    }

    public async Task<AuditEventPage> GetResourceHistoryAsync(string resourceId, int limit)
    {
        var scanRequest = new ScanRequest
        {
            TableName = _settings.DynamoDbTable,
            FilterExpression = "ResourceId = :rid",
            ExpressionAttributeNames = new Dictionary<string, string>(),
            ExpressionAttributeValues = new Dictionary<string, AttributeValue>
            {
                [":rid"] = new AttributeValue { S = resourceId },
            },
        };

        var (keys, total) = await ScanNewestKeysAsync(scanRequest, limit);
        var events = await BatchGetEventsAsync(keys);

        _logger.LogDebug("Retrieved {Count} of {Total} events for resource {ResourceId}", events.Count, total, resourceId);
        return new AuditEventPage
        {
            Events = events,
            Total = total,
            Page = 1,
            PageSize = limit,
        };
    }

    public IAsyncEnumerable<AuditEvent> StreamEventsByDateRangeAsync(
        DateTime from, DateTime to, CancellationToken cancellationToken = default)
    {
        var scanRequest = new ScanRequest
        {
            TableName = _settings.DynamoDbTable,
            FilterExpression = "#ts >= :fromTs AND #ts <= :toTs",
            ExpressionAttributeNames = new Dictionary<string, string>
            {
                ["#ts"] = "Timestamp",
            },
            ExpressionAttributeValues = new Dictionary<string, AttributeValue>
            {
                [":fromTs"] = new AttributeValue { S = from.ToString("O") },
                [":toTs"] = new AttributeValue { S = to.ToString("O") },
            },
        };

        return StreamScanAsync(scanRequest, cancellationToken);
    }

    private async IAsyncEnumerable<AuditEvent> StreamScanAsync(
        ScanRequest scanRequest, [EnumeratorCancellation] CancellationToken cancellationToken)
    {
        scanRequest.Limit = _limits.ScanPageSize;
        ScanResponse? response = null;

        do
        {
            if (response?.LastEvaluatedKey?.Count > 0)
                scanRequest.ExclusiveStartKey = response.LastEvaluatedKey;

            response = await _dynamoDb.ScanAsync(scanRequest, cancellationToken);
            foreach (var item in response.Items)
                yield return MapToAuditEvent(item);
        }
        while (response.LastEvaluatedKey?.Count > 0);
    }

    // Scans only the key and timestamp of matching items and keeps the newest `keep` of them,
    // so memory is bounded by `keep` regardless of how large the table is.
    private async Task<(List<EventKey> Keys, int Total)> ScanNewestKeysAsync(ScanRequest scanRequest, int keep)
    {
        scanRequest.ExpressionAttributeNames ??= new Dictionary<string, string>();
        scanRequest.ExpressionAttributeNames["#pk"] = "id";
        scanRequest.ExpressionAttributeNames["#ts"] = "Timestamp";
        scanRequest.ProjectionExpression = "#pk, #ts";
        scanRequest.Limit = _limits.ScanPageSize;

        var newest = new SortedSet<EventKey>(EventKey.NewestFirst);
        var total = 0;
        ScanResponse? response = null;

        do
        {
            if (response?.LastEvaluatedKey?.Count > 0)
                scanRequest.ExclusiveStartKey = response.LastEvaluatedKey;

            response = await _dynamoDb.ScanAsync(scanRequest);
            foreach (var item in response.Items)
            {
                total++;
                if (keep <= 0)
                    continue;

                newest.Add(MapToEventKey(item));
                if (newest.Count > keep)
                    newest.Remove(newest.Max!);
            }
        }
        while (response.LastEvaluatedKey?.Count > 0);

        return (newest.ToList(), total);
    }

    private async Task<List<AuditEvent>> BatchGetEventsAsync(IReadOnlyList<EventKey> keys)
    {
        const int batchSize = 100;
        var found = new Dictionary<string, AuditEvent>();

        for (var i = 0; i < keys.Count; i += batchSize)
        {
            var request = new BatchGetItemRequest
            {
                RequestItems = new Dictionary<string, KeysAndAttributes>
                {
                    [_settings.DynamoDbTable] = new KeysAndAttributes
                    {
                        Keys = keys.Skip(i).Take(batchSize)
                            .Select(k => new Dictionary<string, AttributeValue> { ["id"] = new AttributeValue { S = k.Id } })
                            .ToList(),
                    },
                },
            };

            var retryCount = 0;
            while (true)
            {
                var response = await _dynamoDb.BatchGetItemAsync(request);
                if (response.Responses is not null &&
                    response.Responses.TryGetValue(_settings.DynamoDbTable, out var items))
                {
                    foreach (var item in items)
                    {
                        var key = MapToEventKey(item);
                        found[key.Id] = MapToAuditEvent(item);
                    }
                }

                if (response.UnprocessedKeys is null || response.UnprocessedKeys.Count == 0)
                    break;

                if (retryCount >= 5)
                    throw new InvalidOperationException("DynamoDB left audit event keys unprocessed after retries; refusing to return a partial page.");

                retryCount++;
                await Task.Delay((int)Math.Pow(2, retryCount) * 100);
                request = new BatchGetItemRequest { RequestItems = response.UnprocessedKeys };
            }
        }

        return keys.Where(k => found.ContainsKey(k.Id)).Select(k => found[k.Id]).ToList();
    }

    private static EventKey MapToEventKey(Dictionary<string, AttributeValue> item)
    {
        var id = item.TryGetValue("id", out var lowerId)
            ? lowerId.S
            : item.TryGetValue("Id", out var upperId) ? upperId.S : string.Empty;
        var timestamp = item.TryGetValue("Timestamp", out var ts) && DateTime.TryParse(ts.S, null, System.Globalization.DateTimeStyles.RoundtripKind, out var parsedTs)
            ? parsedTs
            : DateTime.MinValue;
        return new EventKey(id, timestamp);
    }

    private sealed record EventKey(string Id, DateTime Timestamp)
    {
        public static readonly IComparer<EventKey> NewestFirst = Comparer<EventKey>.Create((a, b) =>
        {
            var byTime = b.Timestamp.CompareTo(a.Timestamp);
            return byTime != 0 ? byTime : string.CompareOrdinal(a.Id, b.Id);
        });
    }

    public async Task<int> DeleteEventsAsync(IEnumerable<string> eventIds)
    {
        var idList = eventIds.ToList();
        const int batchSize = 25;
        var totalFailed = 0;

        for (var i = 0; i < idList.Count; i += batchSize)
        {
            var batch = idList.Skip(i).Take(batchSize).ToList();
            var writeRequests = batch.Select(id => new WriteRequest
            {
                DeleteRequest = new DeleteRequest
                {
                    Key = new Dictionary<string, AttributeValue>
                    {
                        ["id"] = new AttributeValue { S = id },
                    },
                },
            }).ToList();

            var batchRequest = new BatchWriteItemRequest
            {
                RequestItems = new Dictionary<string, List<WriteRequest>>
                {
                    [_settings.DynamoDbTable] = writeRequests,
                },
            };

            var batchResponse = await _dynamoDb.BatchWriteItemAsync(batchRequest);

            var retryCount = 0;
            while (batchResponse.UnprocessedItems.Count > 0 && retryCount < 5)
            {
                retryCount++;
                var delayMs = (int)Math.Pow(2, retryCount) * 100;
                _logger.LogWarning("Retrying {Count} unprocessed delete items (attempt {Retry})",
                    batchResponse.UnprocessedItems.Values.Sum(v => v.Count), retryCount);
                await Task.Delay(delayMs);
                batchResponse = await _dynamoDb.BatchWriteItemAsync(new BatchWriteItemRequest
                {
                    RequestItems = batchResponse.UnprocessedItems,
                });
            }

            if (batchResponse.UnprocessedItems.Count > 0)
            {
                var failedCount = batchResponse.UnprocessedItems.Values.Sum(v => v.Count);
                totalFailed += failedCount;
                _logger.LogError("Failed to delete {Count} items after retries", failedCount);
            }
        }

        var deleted = idList.Count - totalFailed;
        _logger.LogInformation("Deleted {Deleted} of {Total} audit events from DynamoDB", deleted, idList.Count);
        return deleted;
    }

    private static AuditEvent MapToAuditEvent(Dictionary<string, AttributeValue> item)
    {
        var auditEvent = new AuditEvent
        {
            Id = item.TryGetValue("Id", out var id)
                ? id.S
                : item.TryGetValue("id", out var lowerId) ? lowerId.S : string.Empty,
            UserId = item.TryGetValue("UserId", out var uid) ? uid.S : string.Empty,
            Action = item.TryGetValue("Action", out var act) ? act.S : string.Empty,
            ResourceType = item.TryGetValue("ResourceType", out var rt) ? rt.S : string.Empty,
            ResourceId = item.TryGetValue("ResourceId", out var rid) ? rid.S : string.Empty,
            Timestamp = item.TryGetValue("Timestamp", out var ts) && DateTime.TryParse(ts.S, null, System.Globalization.DateTimeStyles.RoundtripKind, out var parsedTs)
                ? parsedTs
                : DateTime.MinValue,
            IpAddress = item.TryGetValue("IpAddress", out var ip) ? ip.S : null,
            UserAgent = item.TryGetValue("UserAgent", out var ua) ? ua.S : null,
        };

        if (item.TryGetValue("Details", out var details) && details.M is not null)
        {
            auditEvent.Details = details.M.ToDictionary(
                kvp => kvp.Key,
                kvp => kvp.Value.S);
        }

        return auditEvent;
    }
}
