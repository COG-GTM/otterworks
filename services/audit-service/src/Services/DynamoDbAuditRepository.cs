using System.Globalization;
using System.Text.Json;
using System.Text.Json.Serialization;
using Amazon.DynamoDBv2;
using Amazon.DynamoDBv2.Model;
using Microsoft.Extensions.Options;
using OtterWorks.AuditService.Config;

namespace OtterWorks.AuditService.Services;

public class DynamoDbAuditRepository : IAuditRepository
{
    // Key attributes of the table's GSIs (see infrastructure/terraform/modules/database/main.tf).
    internal const string UserIdAttribute = "user_id";
    internal const string ResourceIdAttribute = "resource_id";
    internal const string TimestampAttribute = "timestamp";
    internal const string DatePartitionAttribute = "date_partition";
    private const string PartitionFormat = "yyyy-MM-dd";
    private const int MaxCursorLength = 4096;

    private static readonly HashSet<string> CursorKeyAttributes = new(StringComparer.Ordinal)
    {
        "id", UserIdAttribute, ResourceIdAttribute, TimestampAttribute, DatePartitionAttribute,
    };

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
        };

        var timestamp = ToUtc(auditEvent.Timestamp);
        item[TimestampAttribute] = new AttributeValue { S = FormatTimestamp(timestamp) };
        item[DatePartitionAttribute] = new AttributeValue { S = FormatPartition(timestamp) };
        if (!string.IsNullOrEmpty(auditEvent.UserId))
            item[UserIdAttribute] = new AttributeValue { S = auditEvent.UserId };
        if (!string.IsNullOrEmpty(auditEvent.ResourceId))
            item[ResourceIdAttribute] = new AttributeValue { S = auditEvent.ResourceId };

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

    public async Task<AuditEventPage> QueryEventsAsync(AuditEventQuery query)
    {
        var (from, to) = ResolveWindow(query.From, query.To);
        var pageSize = Math.Clamp(query.PageSize, 1, 100);

        var filters = new FilterBuilder();
        filters.AddEquals("Action", query.Action);
        filters.AddEquals("ResourceType", query.ResourceType);

        ReadPlan plan;
        if (!string.IsNullOrEmpty(query.UserId))
        {
            filters.AddEquals("ResourceId", query.ResourceId);
            plan = ReadPlan.ForPartition(_settings.DynamoDbUserIndex, UserIdAttribute, query.UserId);
        }
        else if (!string.IsNullOrEmpty(query.ResourceId) && !string.IsNullOrEmpty(_settings.DynamoDbResourceIndex))
        {
            plan = ReadPlan.ForPartition(_settings.DynamoDbResourceIndex, ResourceIdAttribute, query.ResourceId);
        }
        else
        {
            filters.AddEquals("ResourceId", query.ResourceId);
            plan = ReadPlan.ForDays(_settings.DynamoDbTimestampIndex, from, to);
        }

        var page = await ReadBoundedAsync(plan, from, to, filters, query.Cursor, pageSize, _settings.MaxItemsEvaluatedPerRequest);
        _logger.LogDebug("Queried audit events: userId={UserId}, action={Action}, returned={Count}, hasMore={HasMore}",
            query.UserId, query.Action, page.Events.Count, page.HasMore);
        return page;
    }

    public async Task<AuditEventPage> GetUserEventsAsync(string userId, DateTime from, DateTime to, int maxEvents)
    {
        var (start, end) = ResolveWindow(from, to);
        var limit = Math.Clamp(maxEvents, 1, _settings.MaxEventsPerReport);
        var plan = ReadPlan.ForPartition(_settings.DynamoDbUserIndex, UserIdAttribute, userId);

        var page = await ReadBoundedAsync(plan, start, end, new FilterBuilder(), null, limit, limit);
        _logger.LogDebug("Retrieved {Count} events for user {UserId} (hasMore={HasMore})", page.Events.Count, userId, page.HasMore);
        return page;
    }

    public async Task<AuditEventPage> GetResourceHistoryAsync(string resourceId, string? cursor, int pageSize)
    {
        var (from, to) = ResolveWindow(null, null);
        var size = Math.Clamp(pageSize, 1, 100);
        var filters = new FilterBuilder();

        ReadPlan plan;
        if (!string.IsNullOrEmpty(_settings.DynamoDbResourceIndex))
        {
            plan = ReadPlan.ForPartition(_settings.DynamoDbResourceIndex, ResourceIdAttribute, resourceId);
        }
        else
        {
            filters.AddEquals("ResourceId", resourceId);
            plan = ReadPlan.ForDays(_settings.DynamoDbTimestampIndex, from, to);
        }

        var page = await ReadBoundedAsync(plan, from, to, filters, cursor, size, _settings.MaxItemsEvaluatedPerRequest);
        _logger.LogDebug("Retrieved {Count} events for resource {ResourceId} (hasMore={HasMore})", page.Events.Count, resourceId, page.HasMore);
        return page;
    }

    public async Task<AuditEventPage> GetEventsByDateRangeAsync(DateTime from, DateTime to, int maxEvents)
    {
        var (start, end) = ResolveWindow(from, to);
        var limit = Math.Clamp(maxEvents, 1, _settings.MaxEventsPerReport);
        var plan = ReadPlan.ForDays(_settings.DynamoDbTimestampIndex, start, end);
        return await ReadBoundedAsync(plan, start, end, new FilterBuilder(), null, limit, limit);
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

    private async Task<AuditEventPage> ReadBoundedAsync(
        ReadPlan plan, DateTime from, DateTime to, FilterBuilder filters, string? cursor, int maxResults, int maxEvaluated)
    {
        var partitions = plan.Partitions;
        var (partitionIndex, startKey) = DecodeCursor(cursor, plan);
        var events = new List<AuditEvent>();
        var evaluated = 0;

        while (partitionIndex < partitions.Count && events.Count < maxResults && evaluated < maxEvaluated)
        {
            var request = BuildQuery(plan, partitions[partitionIndex], from, to, filters);
            request.Limit = Math.Min(maxResults - events.Count, maxEvaluated - evaluated);
            if (startKey is not null)
                request.ExclusiveStartKey = startKey;

            var response = await _dynamoDb.QueryAsync(request);
            evaluated += Math.Max(response.ScannedCount, 1);
            events.AddRange((response.Items ?? new()).Select(MapToAuditEvent));

            if (response.LastEvaluatedKey?.Count > 0)
            {
                startKey = response.LastEvaluatedKey;
            }
            else
            {
                startKey = null;
                partitionIndex++;
            }
        }

        string? nextCursor = null;
        if (partitionIndex < partitions.Count)
            nextCursor = EncodeCursor(plan.IsDayRange ? partitions[partitionIndex] : null, startKey);

        return new AuditEventPage
        {
            Events = events,
            PageSize = maxResults,
            NextCursor = nextCursor,
        };
    }

    private QueryRequest BuildQuery(ReadPlan plan, string partition, DateTime from, DateTime to, FilterBuilder filters)
    {
        var names = new Dictionary<string, string>(filters.Names)
        {
            ["#pk"] = plan.PartitionAttribute,
            ["#ts"] = TimestampAttribute,
        };
        var values = new Dictionary<string, AttributeValue>(filters.Values)
        {
            [":pk"] = new AttributeValue { S = partition },
            [":fromTs"] = new AttributeValue { S = FormatTimestamp(from) },
            [":toTs"] = new AttributeValue { S = FormatTimestamp(to) },
        };

        var request = new QueryRequest
        {
            TableName = _settings.DynamoDbTable,
            IndexName = plan.IndexName,
            KeyConditionExpression = "#pk = :pk AND #ts BETWEEN :fromTs AND :toTs",
            ExpressionAttributeNames = names,
            ExpressionAttributeValues = values,
            ScanIndexForward = false,
        };

        if (filters.Expressions.Count > 0)
            request.FilterExpression = string.Join(" AND ", filters.Expressions);

        return request;
    }

    private (DateTime from, DateTime to) ResolveWindow(DateTime? from, DateTime? to)
    {
        var end = to.HasValue ? ToUtc(to.Value) : DateTime.UtcNow;
        var start = from.HasValue ? ToUtc(from.Value) : end.AddDays(-_settings.DefaultQueryLookbackDays);

        if (start > end)
            throw new InvalidAuditQueryException("'from' must not be after 'to'.");
        if (end - start > TimeSpan.FromDays(_settings.MaxQueryWindowDays))
            throw new InvalidAuditQueryException($"Date range must not exceed {_settings.MaxQueryWindowDays} days.");

        return (start, end);
    }

    private (int partitionIndex, Dictionary<string, AttributeValue>? startKey) DecodeCursor(string? cursor, ReadPlan plan)
    {
        if (string.IsNullOrEmpty(cursor))
            return (0, null);
        if (cursor.Length > MaxCursorLength)
            throw new InvalidAuditQueryException("Invalid cursor.");

        CursorPayload? payload;
        try
        {
            var padded = cursor.Replace('-', '+').Replace('_', '/');
            padded = padded.PadRight(padded.Length + ((4 - padded.Length % 4) % 4), '=');
            payload = JsonSerializer.Deserialize<CursorPayload>(Convert.FromBase64String(padded));
        }
        catch (Exception ex) when (ex is FormatException or JsonException)
        {
            throw new InvalidAuditQueryException("Invalid cursor.");
        }

        if (payload is null)
            throw new InvalidAuditQueryException("Invalid cursor.");

        var partitionIndex = 0;
        if (plan.IsDayRange)
        {
            partitionIndex = payload.P is null ? -1 : plan.Partitions.IndexOf(payload.P);
            if (partitionIndex < 0)
                throw new InvalidAuditQueryException("Cursor does not match the requested date range.");
        }
        else if (payload.P is not null)
        {
            throw new InvalidAuditQueryException("Invalid cursor.");
        }

        if (payload.K is null || payload.K.Count == 0)
            return (partitionIndex, null);

        if (payload.K.Count > CursorKeyAttributes.Count ||
            payload.K.Any(kvp => !CursorKeyAttributes.Contains(kvp.Key) || string.IsNullOrEmpty(kvp.Value) || kvp.Value.Length > 1024) ||
            !payload.K.ContainsKey("id") || !payload.K.ContainsKey(TimestampAttribute) ||
            !payload.K.TryGetValue(plan.PartitionAttribute, out var keyPartition) ||
            keyPartition != plan.Partitions[partitionIndex])
        {
            throw new InvalidAuditQueryException("Cursor does not match the requested query.");
        }

        var startKey = payload.K.ToDictionary(kvp => kvp.Key, kvp => new AttributeValue { S = kvp.Value });
        return (partitionIndex, startKey);
    }

    private static string EncodeCursor(string? partition, Dictionary<string, AttributeValue>? startKey)
    {
        var payload = new CursorPayload
        {
            P = partition,
            K = startKey?.ToDictionary(kvp => kvp.Key, kvp => kvp.Value.S),
        };
        return Convert.ToBase64String(JsonSerializer.SerializeToUtf8Bytes(payload))
            .TrimEnd('=').Replace('+', '-').Replace('/', '_');
    }

    private static DateTime ToUtc(DateTime value) => value.Kind switch
    {
        DateTimeKind.Utc => value,
        DateTimeKind.Local => value.ToUniversalTime(),
        _ => DateTime.SpecifyKind(value, DateTimeKind.Utc),
    };

    private static string FormatTimestamp(DateTime utc) => utc.ToString("O", CultureInfo.InvariantCulture);

    private static string FormatPartition(DateTime utc) => utc.ToString(PartitionFormat, CultureInfo.InvariantCulture);

    private sealed class ReadPlan
    {
        public required string IndexName { get; init; }
        public required string PartitionAttribute { get; init; }
        public required List<string> Partitions { get; init; }
        public bool IsDayRange { get; init; }

        public static ReadPlan ForPartition(string indexName, string attribute, string value) => new()
        {
            IndexName = indexName,
            PartitionAttribute = attribute,
            Partitions = new List<string> { value },
        };

        // Newest day first so results come back in descending timestamp order across partitions.
        public static ReadPlan ForDays(string indexName, DateTime from, DateTime to)
        {
            var days = new List<string>();
            for (var day = to.Date; day >= from.Date; day = day.AddDays(-1))
                days.Add(FormatPartition(day));

            return new ReadPlan
            {
                IndexName = indexName,
                PartitionAttribute = DatePartitionAttribute,
                Partitions = days,
                IsDayRange = true,
            };
        }
    }

    private sealed class FilterBuilder
    {
        public List<string> Expressions { get; } = new();
        public Dictionary<string, string> Names { get; } = new();
        public Dictionary<string, AttributeValue> Values { get; } = new();

        public void AddEquals(string attribute, string? value)
        {
            if (string.IsNullOrEmpty(value))
                return;

            var n = Expressions.Count;
            Expressions.Add($"#f{n} = :f{n}");
            Names[$"#f{n}"] = attribute;
            Values[$":f{n}"] = new AttributeValue { S = value };
        }
    }

    private sealed class CursorPayload
    {
        [JsonPropertyName("p")]
        public string? P { get; set; }

        [JsonPropertyName("k")]
        public Dictionary<string, string>? K { get; set; }
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
