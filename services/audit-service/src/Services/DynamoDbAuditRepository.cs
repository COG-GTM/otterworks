using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Amazon.DynamoDBv2;
using Amazon.DynamoDBv2.Model;
using Microsoft.Extensions.Options;
using OtterWorks.AuditService.Config;

namespace OtterWorks.AuditService.Services;

public class DynamoDbAuditRepository : IAuditRepository
{
    // Key attributes of the table's GSIs (infrastructure/terraform/modules/database/main.tf).
    public const string UserIndex = "user-index";
    public const string TimestampIndex = "timestamp-index";
    public const string UserIdKey = "user_id";
    public const string TimestampKey = "timestamp";
    public const string DatePartitionKey = "date_partition";

    private readonly IAmazonDynamoDB _dynamoDb;
    private readonly AwsSettings _settings;
    private readonly ILogger<DynamoDbAuditRepository> _logger;

    public DynamoDbAuditRepository(
        IAmazonDynamoDB dynamoDb,
        IOptions<AwsSettings> settings,
        ILogger<DynamoDbAuditRepository> logger)
    {
        _dynamoDb = dynamoDb;
        _settings = settings.Value;
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
            [UserIdKey] = new AttributeValue { S = auditEvent.UserId },
            [TimestampKey] = new AttributeValue { S = FormatTimestamp(auditEvent.Timestamp) },
            [DatePartitionKey] = new AttributeValue { S = FormatDatePartition(auditEvent.Timestamp) },
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
        DateTime? from, DateTime? to, int page, int pageSize, string? cursor)
    {
        var fingerprint = Fingerprint(userId, action, resourceType, resourceId, from, to);
        AuditQuery query;
        QueryPosition? start = null;
        var skip = 0;

        if (!string.IsNullOrEmpty(cursor))
        {
            var decoded = DecodeCursor(cursor, fingerprint);
            query = new AuditQuery(userId, action, resourceType, resourceId, decoded.From, decoded.To);
            start = ValidatePosition(BuildPlan(query), decoded);
        }
        else
        {
            var resolvedTo = from.HasValue && !to.HasValue
                ? ToUtc(from.Value).AddDays(AuditQueryLimits.DefaultWindowDays)
                : to.HasValue ? ToUtc(to.Value) : DateTime.UtcNow;
            var resolvedFrom = from.HasValue
                ? ToUtc(from.Value)
                : resolvedTo.AddDays(-AuditQueryLimits.DefaultWindowDays);
            query = new AuditQuery(userId, action, resourceType, resourceId, resolvedFrom, resolvedTo);

            skip = (Math.Max(page, 1) - 1) * pageSize;
            if (skip > AuditQueryLimits.MaxPageOffset)
                throw new AuditQueryException(
                    $"Page offset must not exceed {AuditQueryLimits.MaxPageOffset} events; use the 'cursor' from the previous response.");
        }

        AuditQueryLimits.EnsureRange(query.From, query.To);

        var plan = BuildPlan(query);
        var (events, next, calls) = await ReadAsync(plan, query, skip + pageSize, AuditQueryLimits.MaxCallsPerPage, start);
        var paged = events.Skip(skip).ToList();

        _logger.LogDebug("Queried audit events: userId={UserId}, action={Action}, returned={Count}, calls={Calls}",
            userId, action, paged.Count, calls);
        return new AuditEventPage
        {
            Events = paged,
            Total = paged.Count,
            Page = page,
            PageSize = pageSize,
            NextCursor = next is null ? null : EncodeCursor(fingerprint, query, next),
            HasMore = next is not null,
        };
    }

    public async Task<AuditEventBatch> GetUserEventsAsync(string userId, DateTime from, DateTime to, int maxEvents)
    {
        var query = new AuditQuery(userId, null, null, null, ToUtc(from), ToUtc(to));
        var batch = await CollectAsync(query, maxEvents);
        _logger.LogDebug("Retrieved {Count} events for user {UserId} (truncated={Truncated})",
            batch.Events.Count, userId, batch.Truncated);
        return batch;
    }

    public async Task<AuditEventBatch> GetEventsByDateRangeAsync(DateTime from, DateTime to, int maxEvents)
    {
        var query = new AuditQuery(null, null, null, null, ToUtc(from), ToUtc(to));
        return await CollectAsync(query, maxEvents);
    }

    private async Task<AuditEventBatch> CollectAsync(AuditQuery query, int maxEvents)
    {
        if (query.From > query.To)
            return new AuditEventBatch();

        var (events, next, _) = await ReadAsync(BuildPlan(query), query, maxEvents, AuditQueryLimits.MaxCallsPerCollection, null);
        return new AuditEventBatch { Events = events, Truncated = next is not null };
    }

    // Reads at most maxEvents items with at most maxCalls DynamoDB Query calls, newest first.
    private async Task<(List<AuditEvent> Events, QueryPosition? Next, int Calls)> ReadAsync(
        QueryPlan plan, AuditQuery query, int maxEvents, int maxCalls, QueryPosition? start)
    {
        var events = new List<AuditEvent>();
        var partition = start?.Partition ?? 0;
        var startKey = start?.Key;
        var calls = 0;

        while (partition < plan.Partitions.Count && events.Count < maxEvents && calls < maxCalls)
        {
            var limit = Math.Min(maxEvents - events.Count, AuditQueryLimits.MaxItemsPerCall);
            var request = BuildQueryRequest(plan, plan.Partitions[partition], query, limit, startKey);
            var response = await _dynamoDb.QueryAsync(request);
            calls++;
            events.AddRange(response.Items.Select(MapToAuditEvent));

            if (response.LastEvaluatedKey?.Count > 0)
            {
                startKey = response.LastEvaluatedKey;
            }
            else
            {
                partition++;
                startKey = null;
            }
        }

        var next = partition < plan.Partitions.Count ? new QueryPosition(partition, startKey) : null;
        return (events, next, calls);
    }

    private QueryRequest BuildQueryRequest(
        QueryPlan plan, string partitionValue, AuditQuery query, int limit,
        Dictionary<string, AttributeValue>? startKey)
    {
        var names = new Dictionary<string, string>
        {
            ["#pk"] = plan.PartitionAttribute,
            ["#ts"] = TimestampKey,
        };
        var values = new Dictionary<string, AttributeValue>
        {
            [":pk"] = new AttributeValue { S = partitionValue },
            [":fromTs"] = new AttributeValue { S = FormatTimestamp(query.From) },
            [":toTs"] = new AttributeValue { S = FormatTimestamp(query.To) },
        };
        var filters = new List<string>();

        void AddFilter(string? value, string alias, string attribute)
        {
            if (string.IsNullOrEmpty(value))
                return;
            filters.Add($"#{alias} = :{alias}");
            names[$"#{alias}"] = attribute;
            values[$":{alias}"] = new AttributeValue { S = value };
        }

        AddFilter(query.Action, "act", "Action");
        AddFilter(query.ResourceType, "rt", "ResourceType");
        AddFilter(query.ResourceId, "rid", "ResourceId");

        var request = new QueryRequest
        {
            TableName = _settings.DynamoDbTable,
            IndexName = plan.IndexName,
            KeyConditionExpression = "#pk = :pk AND #ts BETWEEN :fromTs AND :toTs",
            ExpressionAttributeNames = names,
            ExpressionAttributeValues = values,
            ScanIndexForward = false,
            Limit = limit,
        };

        if (filters.Count > 0)
            request.FilterExpression = string.Join(" AND ", filters);

        if (startKey is not null)
            request.ExclusiveStartKey = startKey;

        return request;
    }

    private static QueryPlan BuildPlan(AuditQuery query)
    {
        if (!string.IsNullOrEmpty(query.UserId))
            return new QueryPlan(UserIndex, UserIdKey, new[] { query.UserId! });

        var partitions = new List<string>();
        for (var day = query.To.Date; day >= query.From.Date; day = day.AddDays(-1))
            partitions.Add(FormatDatePartition(day));

        return new QueryPlan(TimestampIndex, DatePartitionKey, partitions);
    }

    private static readonly HashSet<string> CursorKeyAttributes = new() { "id", UserIdKey, DatePartitionKey, TimestampKey };

    private static string EncodeCursor(string fingerprint, AuditQuery query, QueryPosition position)
    {
        var payload = new CursorPayload
        {
            H = fingerprint,
            F = query.From.Ticks,
            T = query.To.Ticks,
            P = position.Partition,
            K = position.Key?.ToDictionary(kvp => kvp.Key, kvp => kvp.Value.S),
        };
        var bytes = JsonSerializer.SerializeToUtf8Bytes(payload);
        return Convert.ToBase64String(bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_');
    }

    private static DecodedCursor DecodeCursor(string cursor, string fingerprint)
    {
        CursorPayload? payload;
        try
        {
            var base64 = cursor.Replace('-', '+').Replace('_', '/');
            base64 = base64.PadRight(base64.Length + ((4 - (base64.Length % 4)) % 4), '=');
            payload = JsonSerializer.Deserialize<CursorPayload>(Convert.FromBase64String(base64));
        }
        catch (Exception ex) when (ex is FormatException or JsonException or ArgumentException)
        {
            throw new AuditQueryException("Invalid cursor.");
        }

        if (payload is null ||
            payload.H != fingerprint ||
            payload.F < DateTime.MinValue.Ticks || payload.F > DateTime.MaxValue.Ticks ||
            payload.T < DateTime.MinValue.Ticks || payload.T > DateTime.MaxValue.Ticks)
        {
            throw new AuditQueryException("Invalid cursor for this query.");
        }

        return new DecodedCursor(
            new DateTime(payload.F, DateTimeKind.Utc),
            new DateTime(payload.T, DateTimeKind.Utc),
            payload.P,
            payload.K);
    }

    private static QueryPosition ValidatePosition(QueryPlan plan, DecodedCursor cursor)
    {
        if (cursor.Partition < 0 || cursor.Partition >= plan.Partitions.Count)
            throw new AuditQueryException("Invalid cursor for this query.");

        if (cursor.Key is null)
            return new QueryPosition(cursor.Partition, null);

        if (cursor.Key.Count > CursorKeyAttributes.Count ||
            cursor.Key.Any(kvp => !CursorKeyAttributes.Contains(kvp.Key) || string.IsNullOrEmpty(kvp.Value)) ||
            !cursor.Key.ContainsKey("id") ||
            !cursor.Key.ContainsKey(TimestampKey) ||
            !cursor.Key.TryGetValue(plan.PartitionAttribute, out var partitionValue) ||
            partitionValue != plan.Partitions[cursor.Partition])
        {
            throw new AuditQueryException("Invalid cursor for this query.");
        }

        return new QueryPosition(
            cursor.Partition,
            cursor.Key.ToDictionary(kvp => kvp.Key, kvp => new AttributeValue { S = kvp.Value }));
    }

    private static string Fingerprint(
        string? userId, string? action, string? resourceType, string? resourceId, DateTime? from, DateTime? to)
    {
        var raw = string.Join("\n",
            userId ?? string.Empty,
            action ?? string.Empty,
            resourceType ?? string.Empty,
            resourceId ?? string.Empty,
            from.HasValue ? FormatTimestamp(from.Value) : string.Empty,
            to.HasValue ? FormatTimestamp(to.Value) : string.Empty);
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(raw)))[..16];
    }

    private static DateTime ToUtc(DateTime value) => value.Kind switch
    {
        DateTimeKind.Local => value.ToUniversalTime(),
        DateTimeKind.Unspecified => DateTime.SpecifyKind(value, DateTimeKind.Utc),
        _ => value,
    };

    private static string FormatTimestamp(DateTime value) =>
        ToUtc(value).ToString("yyyy-MM-dd'T'HH:mm:ss.fffffff'Z'", CultureInfo.InvariantCulture);

    private static string FormatDatePartition(DateTime value) =>
        ToUtc(value).ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);

    private sealed record AuditQuery(
        string? UserId, string? Action, string? ResourceType, string? ResourceId, DateTime From, DateTime To);

    private sealed record QueryPlan(string IndexName, string PartitionAttribute, IReadOnlyList<string> Partitions);

    private sealed record QueryPosition(int Partition, Dictionary<string, AttributeValue>? Key);

    private sealed record DecodedCursor(DateTime From, DateTime To, int Partition, Dictionary<string, string>? Key);

    private sealed class CursorPayload
    {
        public string H { get; set; } = string.Empty;
        public long F { get; set; }
        public long T { get; set; }
        public int P { get; set; }
        public Dictionary<string, string>? K { get; set; }
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
