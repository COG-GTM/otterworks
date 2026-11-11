using Amazon.DynamoDBv2;
using Amazon.DynamoDBv2.Model;
using System.Globalization;
using Microsoft.Extensions.Options;
using OtterWorks.AuditService.Config;

namespace OtterWorks.AuditService.Services;

public class DynamoDbAuditRepository : IAuditRepository
{
    internal const string GsiUserId = "user_id";
    internal const string GsiTimestamp = "timestamp";
    internal const string GsiDatePartition = "date_partition";
    internal const string PartitionFormat = "yyyy-MM-dd";

    private readonly IAmazonDynamoDB _dynamoDb;
    private readonly AwsSettings _settings;
    private readonly AuditQuerySettings _limits;
    private readonly ILogger<DynamoDbAuditRepository> _logger;

    public DynamoDbAuditRepository(
        IAmazonDynamoDB dynamoDb,
        IOptions<AwsSettings> settings,
        IOptions<AuditQuerySettings> limits,
        ILogger<DynamoDbAuditRepository> logger)
    {
        _dynamoDb = dynamoDb;
        _settings = settings.Value;
        _limits = limits.Value;
        _logger = logger;
    }

    public async Task SaveEventAsync(AuditEvent auditEvent)
    {
        var timestamp = ToUtc(auditEvent.Timestamp);
        var item = new Dictionary<string, AttributeValue>
        {
            ["id"] = new AttributeValue { S = auditEvent.Id },
            ["Id"] = new AttributeValue { S = auditEvent.Id },
            ["UserId"] = new AttributeValue { S = auditEvent.UserId },
            ["Action"] = new AttributeValue { S = auditEvent.Action },
            ["ResourceType"] = new AttributeValue { S = auditEvent.ResourceType },
            ["ResourceId"] = new AttributeValue { S = auditEvent.ResourceId },
            ["Timestamp"] = new AttributeValue { S = timestamp.ToString("O") },
            [GsiTimestamp] = new AttributeValue { S = timestamp.ToString("O") },
            [GsiDatePartition] = new AttributeValue { S = FormatPartition(timestamp) },
        };

        if (!string.IsNullOrEmpty(auditEvent.UserId))
            item[GsiUserId] = new AttributeValue { S = auditEvent.UserId };

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
        DateTime? from, DateTime? to, string? cursor, int pageSize)
    {
        var filter = new QueryFilter(action, resourceType, resourceId);
        var page = string.IsNullOrEmpty(userId)
            ? await QueryDatePartitionPageAsync(filter, from, to, cursor, pageSize)
            : await QueryUserPageAsync(userId, filter, from, to, cursor, pageSize);

        _logger.LogDebug("Queried audit events: userId={UserId}, action={Action}, returned={Count}, hasMore={HasMore}",
            userId, action, page.Events.Count, page.HasMore);
        return page;
    }

    public async Task<AuditEventBatch> GetUserEventsAsync(string userId, DateTime from, DateTime to, int maxItems)
    {
        var (rangeFrom, rangeTo) = NormalizeRange(from, to);
        var request = BuildUserQuery(userId, rangeFrom, rangeTo, QueryFilter.None);
        var batch = await CollectAsync(new[] { request }, maxItems);

        _logger.LogDebug("Retrieved {Count} events for user {UserId} (truncated={Truncated})", batch.Events.Count, userId, batch.Truncated);
        return batch;
    }

    public async Task<AuditEventBatch> GetResourceHistoryAsync(string resourceId, DateTime from, DateTime to, int maxItems)
    {
        var (rangeFrom, rangeTo) = NormalizeRange(from, to);
        var filter = new QueryFilter(null, null, resourceId);
        var requests = DatePartitions(rangeFrom, rangeTo, oldestFirst: false)
            .Select(day => BuildDateQuery(day, rangeFrom, rangeTo, filter));
        var batch = await CollectAsync(requests, maxItems);

        _logger.LogDebug("Retrieved {Count} events for resource {ResourceId} (truncated={Truncated})", batch.Events.Count, resourceId, batch.Truncated);
        return batch;
    }

    public async Task<AuditEventBatch> GetEventsByDateRangeAsync(DateTime from, DateTime to, int maxItems, bool oldestFirst = false)
    {
        var (rangeFrom, rangeTo) = NormalizeRange(from, to);
        var requests = DatePartitions(rangeFrom, rangeTo, oldestFirst)
            .Select(day => BuildDateQuery(day, rangeFrom, rangeTo, QueryFilter.None, oldestFirst));
        var batch = await CollectAsync(requests, maxItems);
        if (oldestFirst)
            batch.Events = batch.Events.OrderBy(e => e.Timestamp).ToList();
        return batch;
    }

    private async Task<AuditEventPage> QueryUserPageAsync(
        string userId, QueryFilter filter, DateTime? from, DateTime? to, string? cursor, int pageSize)
    {
        DateTime? rangeFrom = from.HasValue ? ToUtc(from.Value) : null;
        DateTime? rangeTo = to.HasValue ? ToUtc(to.Value) : null;
        if (rangeFrom > rangeTo)
            throw new ArgumentException("'from' must not be later than 'to'.");

        var state = AuditCursor.Decode(cursor);
        if (state?.Partition is not null)
            throw new ArgumentException("Invalid cursor.");
        var startKey = ValidateStartKey(state?.Key, GsiUserId, userId);

        var request = BuildUserQuery(userId, rangeFrom, rangeTo, filter);
        var events = new List<AuditEvent>();

        for (var calls = 0; calls < _limits.MaxQueryCallsPerPage && events.Count < pageSize; calls++)
        {
            request.Limit = pageSize - events.Count;
            if (startKey is not null)
                request.ExclusiveStartKey = startKey;

            var response = await _dynamoDb.QueryAsync(request);
            events.AddRange(response.Items.Select(MapToAuditEvent));
            startKey = response.LastEvaluatedKey?.Count > 0 ? response.LastEvaluatedKey : null;
            if (startKey is null)
                break;
        }

        return new AuditEventPage
        {
            Events = events,
            Total = events.Count,
            PageSize = pageSize,
            NextCursor = startKey is null ? null : AuditCursor.Encode(null, startKey),
        };
    }

    private async Task<AuditEventPage> QueryDatePartitionPageAsync(
        QueryFilter filter, DateTime? from, DateTime? to, string? cursor, int pageSize)
    {
        var rangeTo = to.HasValue ? ToUtc(to.Value) : DateTime.UtcNow;
        var rangeFrom = from.HasValue ? ToUtc(from.Value) : rangeTo.AddDays(-_limits.DefaultQueryWindowDays);
        (rangeFrom, rangeTo) = NormalizeRange(rangeFrom, rangeTo);

        var state = AuditCursor.Decode(cursor);
        var day = rangeTo.Date;
        Dictionary<string, AttributeValue>? startKey = null;
        if (state is not null)
        {
            if (state.Partition is null ||
                !DateTime.TryParseExact(state.Partition, PartitionFormat, CultureInfo.InvariantCulture,
                    DateTimeStyles.AdjustToUniversal | DateTimeStyles.AssumeUniversal, out var cursorDay) ||
                cursorDay < rangeFrom.Date || cursorDay > rangeTo.Date)
            {
                throw new ArgumentException("Invalid cursor.");
            }

            day = DateTime.SpecifyKind(cursorDay.Date, DateTimeKind.Utc);
            startKey = ValidateStartKey(state.Key, GsiDatePartition, state.Partition);
        }

        var events = new List<AuditEvent>();
        var exhausted = false;

        for (var calls = 0; calls < _limits.MaxQueryCallsPerPage && events.Count < pageSize; calls++)
        {
            var request = BuildDateQuery(day, rangeFrom, rangeTo, filter);
            request.Limit = pageSize - events.Count;
            if (startKey is not null)
                request.ExclusiveStartKey = startKey;

            var response = await _dynamoDb.QueryAsync(request);
            events.AddRange(response.Items.Select(MapToAuditEvent));
            startKey = response.LastEvaluatedKey?.Count > 0 ? response.LastEvaluatedKey : null;

            if (startKey is null)
            {
                day = day.AddDays(-1);
                if (day < rangeFrom.Date)
                {
                    exhausted = true;
                    break;
                }
            }
        }

        return new AuditEventPage
        {
            Events = events,
            Total = events.Count,
            PageSize = pageSize,
            NextCursor = exhausted ? null : AuditCursor.Encode(FormatPartition(day), startKey),
        };
    }

    private async Task<AuditEventBatch> CollectAsync(IEnumerable<QueryRequest> requests, int maxItems)
    {
        var events = new List<AuditEvent>();
        var calls = 0;

        foreach (var request in requests)
        {
            Dictionary<string, AttributeValue>? startKey = null;
            do
            {
                if (events.Count >= maxItems || calls >= _limits.MaxQueryCallsPerBatch)
                {
                    _logger.LogWarning("Audit query stopped after {Calls} DynamoDB calls and {Count} events (maxItems={MaxItems})",
                        calls, events.Count, maxItems);
                    return new AuditEventBatch { Events = events, Truncated = true };
                }

                request.Limit = maxItems - events.Count;
                if (startKey is not null)
                    request.ExclusiveStartKey = startKey;

                var response = await _dynamoDb.QueryAsync(request);
                calls++;
                events.AddRange(response.Items.Select(MapToAuditEvent));
                startKey = response.LastEvaluatedKey?.Count > 0 ? response.LastEvaluatedKey : null;
            }
            while (startKey is not null);
        }

        return new AuditEventBatch { Events = events, Truncated = false };
    }

    private QueryRequest BuildUserQuery(string userId, DateTime? from, DateTime? to, QueryFilter filter)
    {
        var names = new Dictionary<string, string> { ["#guid"] = GsiUserId };
        var values = new Dictionary<string, AttributeValue> { [":guid"] = new AttributeValue { S = userId } };
        var keyCondition = "#guid = :guid";

        if (from.HasValue || to.HasValue)
        {
            names["#gts"] = GsiTimestamp;
            values[":gfrom"] = new AttributeValue { S = (from ?? DateTime.MinValue).ToString("O") };
            values[":gto"] = new AttributeValue { S = (to ?? DateTime.MaxValue).ToString("O") };
            keyCondition += " AND #gts BETWEEN :gfrom AND :gto";
        }

        var request = new QueryRequest
        {
            TableName = _settings.DynamoDbTable,
            IndexName = _limits.UserIndexName,
            KeyConditionExpression = keyCondition,
            ScanIndexForward = false,
        };
        ApplyFilter(request, filter, names, values);
        return request;
    }

    private QueryRequest BuildDateQuery(DateTime day, DateTime from, DateTime to, QueryFilter filter, bool oldestFirst = false)
    {
        var names = new Dictionary<string, string>
        {
            ["#gdp"] = GsiDatePartition,
            ["#gts"] = GsiTimestamp,
        };
        var values = new Dictionary<string, AttributeValue>
        {
            [":gdp"] = new AttributeValue { S = FormatPartition(day) },
            [":gfrom"] = new AttributeValue { S = from.ToString("O") },
            [":gto"] = new AttributeValue { S = to.ToString("O") },
        };

        var request = new QueryRequest
        {
            TableName = _settings.DynamoDbTable,
            IndexName = _limits.DateIndexName,
            KeyConditionExpression = "#gdp = :gdp AND #gts BETWEEN :gfrom AND :gto",
            ScanIndexForward = oldestFirst,
        };
        ApplyFilter(request, filter, names, values);
        return request;
    }

    private static void ApplyFilter(
        QueryRequest request, QueryFilter filter,
        Dictionary<string, string> names, Dictionary<string, AttributeValue> values)
    {
        var filterExpressions = new List<string>();

        if (!string.IsNullOrEmpty(filter.Action))
        {
            filterExpressions.Add("#act = :act");
            names["#act"] = "Action";
            values[":act"] = new AttributeValue { S = filter.Action };
        }

        if (!string.IsNullOrEmpty(filter.ResourceType))
        {
            filterExpressions.Add("ResourceType = :rt");
            values[":rt"] = new AttributeValue { S = filter.ResourceType };
        }

        if (!string.IsNullOrEmpty(filter.ResourceId))
        {
            filterExpressions.Add("ResourceId = :rid");
            values[":rid"] = new AttributeValue { S = filter.ResourceId };
        }

        if (filterExpressions.Count > 0)
            request.FilterExpression = string.Join(" AND ", filterExpressions);

        request.ExpressionAttributeNames = names;
        request.ExpressionAttributeValues = values;
    }

    private (DateTime from, DateTime to) NormalizeRange(DateTime from, DateTime to)
    {
        var rangeFrom = ToUtc(from);
        var rangeTo = ToUtc(to);
        if (rangeFrom > rangeTo)
            throw new ArgumentException("'from' must not be later than 'to'.");
        if ((rangeTo.Date - rangeFrom.Date).TotalDays >= _limits.MaxQueryRangeDays)
            throw new ArgumentException($"Date range must not exceed {_limits.MaxQueryRangeDays} days.");
        return (rangeFrom, rangeTo);
    }

    private static IEnumerable<DateTime> DatePartitions(DateTime from, DateTime to, bool oldestFirst)
    {
        if (oldestFirst)
        {
            for (var day = from.Date; day <= to.Date; day = day.AddDays(1))
                yield return day;
        }
        else
        {
            for (var day = to.Date; day >= from.Date; day = day.AddDays(-1))
                yield return day;
        }
    }

    private static Dictionary<string, AttributeValue>? ValidateStartKey(
        Dictionary<string, string>? key, string partitionAttribute, string expectedPartition)
    {
        if (key is null)
            return null;

        var allowed = new HashSet<string> { "id", GsiTimestamp, partitionAttribute };
        if (key.Count != allowed.Count ||
            !key.Keys.All(allowed.Contains) ||
            key[partitionAttribute] != expectedPartition)
        {
            throw new ArgumentException("Invalid cursor.");
        }

        return key.ToDictionary(kvp => kvp.Key, kvp => new AttributeValue { S = kvp.Value });
    }

    private static DateTime ToUtc(DateTime value) => value.Kind switch
    {
        DateTimeKind.Utc => value,
        DateTimeKind.Local => value.ToUniversalTime(),
        _ => DateTime.SpecifyKind(value, DateTimeKind.Utc),
    };

    private static string FormatPartition(DateTime day) =>
        day.ToString(PartitionFormat, CultureInfo.InvariantCulture);

    private sealed record QueryFilter(string? Action, string? ResourceType, string? ResourceId)
    {
        public static readonly QueryFilter None = new(null, null, null);
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
