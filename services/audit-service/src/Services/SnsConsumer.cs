using System.Text.Json;
using System.Text.Json.Serialization;
using Amazon.SimpleNotificationService;
using Amazon.SimpleNotificationService.Model;
using Amazon.SQS;
using Amazon.SQS.Model;
using Microsoft.Extensions.Options;
using OtterWorks.AuditService.Config;

namespace OtterWorks.AuditService.Services;

public class SnsConsumer : BackgroundService
{
    private readonly IAmazonSQS _sqsClient;
    private readonly IAuditRepository _repository;
    private readonly AwsSettings _settings;
    private readonly ILogger<SnsConsumer> _logger;
    private string? _queueUrl;

    public SnsConsumer(
        IAmazonSQS sqsClient,
        IAuditRepository repository,
        IOptions<AwsSettings> settings,
        ILogger<SnsConsumer> logger)
    {
        _sqsClient = sqsClient;
        _repository = repository;
        _settings = settings.Value;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        _logger.LogInformation("SNS Consumer starting, waiting for audit events...");

        try
        {
            _queueUrl = await GetOrCreateQueueUrlAsync(stoppingToken);
        }
        catch (Exception ex)
        {
            _logger.LogWarning(ex, "Failed to initialize SQS queue. SNS Consumer will not process messages");
            return;
        }

        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                var receiveRequest = new ReceiveMessageRequest
                {
                    QueueUrl = _queueUrl,
                    MaxNumberOfMessages = 10,
                    WaitTimeSeconds = 20,
                };

                var response = await _sqsClient.ReceiveMessageAsync(receiveRequest, stoppingToken);

                foreach (var message in response.Messages)
                {
                    await ProcessMessageAsync(message, stoppingToken);
                }
            }
            catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested)
            {
                break;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error processing SQS messages");
                await Task.Delay(TimeSpan.FromSeconds(5), stoppingToken);
            }
        }

        _logger.LogInformation("SNS Consumer stopping");
    }

    private async Task<string> GetOrCreateQueueUrlAsync(CancellationToken ct)
    {
        const string queueName = "otterworks-audit-events-queue";
        try
        {
            var response = await _sqsClient.GetQueueUrlAsync(queueName, ct);
            return response.QueueUrl;
        }
        catch (QueueDoesNotExistException)
        {
            var createResponse = await _sqsClient.CreateQueueAsync(new CreateQueueRequest
            {
                QueueName = queueName,
            }, ct);
            return createResponse.QueueUrl;
        }
    }

    private async Task ProcessMessageAsync(Message message, CancellationToken ct)
    {
        try
        {
            var snsMessage = TryParseSnsEnvelope(message.Body);
            var eventBody = snsMessage ?? message.Body;

            var fileEvent = JsonSerializer.Deserialize<FileEventMessage>(eventBody, new JsonSerializerOptions
            {
                PropertyNameCaseInsensitive = true,
            });
            if (fileEvent?.EventType == "file_shared")
            {
                var fileShareEvent = new AuditEvent
                {
                    Id = message.MessageId,
                    UserId = fileEvent.OwnerId ?? "system",
                    Action = "share",
                    ResourceType = "file",
                    ResourceId = fileEvent.FileId ?? string.Empty,
                    Details = new Dictionary<string, string>
                    {
                        ["sharedWithUserId"] = fileEvent.SharedWithUserId ?? string.Empty,
                    },
                    Timestamp = fileEvent.Timestamp ?? DateTime.UtcNow,
                };

                await _repository.SaveEventAsync(fileShareEvent);
                _logger.LogDebug("Processed file share SNS event for {FileId}", fileEvent.FileId);
                await _sqsClient.DeleteMessageAsync(_queueUrl, message.ReceiptHandle, ct);
                return;
            }

            var entity = MapAuditEventMessage(eventBody, message.MessageId);

            if (entity is null)
            {
                _logger.LogWarning("Failed to deserialize audit event from message {MessageId}", message.MessageId);
                await _sqsClient.DeleteMessageAsync(_queueUrl, message.ReceiptHandle, ct);
                return;
            }

            await _repository.SaveEventAsync(entity);
            _logger.LogDebug("Processed SNS event: {Action} on {ResourceType}/{ResourceId}",
                entity.Action, entity.ResourceType, entity.ResourceId);

            await _sqsClient.DeleteMessageAsync(_queueUrl, message.ReceiptHandle, ct);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to process message {MessageId}", message.MessageId);
        }
    }

    internal static AuditEvent? MapAuditEventMessage(string eventBody, string messageId)
    {
        var options = new JsonSerializerOptions { PropertyNameCaseInsensitive = true };
        var outer = JsonSerializer.Deserialize<AuditEventMessage>(eventBody, options);

        if (outer is null)
            return null;

        // Python services (EventPublisher) wrap fields as {"event_type", "timestamp", "payload": {...}}.
        var inner = outer.Payload is { ValueKind: JsonValueKind.Object } payload
            ? payload.Deserialize<AuditEventMessage>(options)
            : null;

        return new AuditEvent
        {
            Id = messageId,
            UserId = inner?.ResolvedUserId ?? outer.ResolvedUserId ?? "system",
            Action = inner?.ResolvedAction ?? outer.ResolvedAction ?? "unknown",
            ResourceType = inner?.ResolvedResourceType ?? outer.ResolvedResourceType ?? "unknown",
            ResourceId = inner?.ResolvedResourceId ?? outer.ResolvedResourceId ?? string.Empty,
            Details = inner?.Details ?? outer.Details,
            IpAddress = inner?.ResolvedIpAddress ?? outer.ResolvedIpAddress,
            UserAgent = inner?.ResolvedUserAgent ?? outer.ResolvedUserAgent,
            WorkspaceId = inner?.ResolvedWorkspaceId ?? outer.ResolvedWorkspaceId,
            OldValue = ToJsonString(inner?.ResolvedOldValue) ?? ToJsonString(outer.ResolvedOldValue),
            NewValue = ToJsonString(inner?.ResolvedNewValue) ?? ToJsonString(outer.ResolvedNewValue),
            Timestamp = inner?.Timestamp ?? outer.Timestamp ?? DateTime.UtcNow,
        };
    }

    // Old/new values are stored as serialized JSON strings; publishers may send either a
    // pre-serialized string or a raw JSON value.
    private static string? ToJsonString(JsonElement? value) => value?.ValueKind switch
    {
        null or JsonValueKind.Undefined or JsonValueKind.Null => null,
        JsonValueKind.String => value.Value.GetString(),
        _ => value.Value.GetRawText(),
    };

    private static string? TryParseSnsEnvelope(string body)
    {
        try
        {
            using var doc = JsonDocument.Parse(body);
            if (doc.RootElement.TryGetProperty("Message", out var messageElement))
            {
                return messageElement.GetString();
            }
        }
        catch (JsonException)
        {
            // Not an SNS envelope
        }

        return null;
    }

    private sealed class AuditEventMessage
    {
        public string? UserId { get; set; }
        public string? Action { get; set; }
        public string? ResourceType { get; set; }
        public string? ResourceId { get; set; }
        public Dictionary<string, string>? Details { get; set; }
        public string? IpAddress { get; set; }
        public string? UserAgent { get; set; }
        public string? WorkspaceId { get; set; }
        public JsonElement? OldValue { get; set; }
        public JsonElement? NewValue { get; set; }
        public DateTime? Timestamp { get; set; }
        public JsonElement? Payload { get; set; }

        [JsonPropertyName("user_id")]
        public string? UserIdSnake { get; set; }

        [JsonPropertyName("actor_id")]
        public string? ActorIdSnake { get; set; }

        [JsonPropertyName("event_type")]
        public string? EventTypeSnake { get; set; }

        [JsonPropertyName("resource_type")]
        public string? ResourceTypeSnake { get; set; }

        [JsonPropertyName("resource_id")]
        public string? ResourceIdSnake { get; set; }

        [JsonPropertyName("ip_address")]
        public string? IpAddressSnake { get; set; }

        [JsonPropertyName("user_agent")]
        public string? UserAgentSnake { get; set; }

        [JsonPropertyName("workspace_id")]
        public string? WorkspaceIdSnake { get; set; }

        [JsonPropertyName("old_value")]
        public JsonElement? OldValueSnake { get; set; }

        [JsonPropertyName("new_value")]
        public JsonElement? NewValueSnake { get; set; }

        public string? ResolvedUserId => UserId ?? UserIdSnake ?? ActorIdSnake;
        public string? ResolvedAction => Action ?? EventTypeSnake;
        public string? ResolvedResourceType => ResourceType ?? ResourceTypeSnake;
        public string? ResolvedResourceId => ResourceId ?? ResourceIdSnake;
        public string? ResolvedIpAddress => IpAddress ?? IpAddressSnake;
        public string? ResolvedUserAgent => UserAgent ?? UserAgentSnake;
        public string? ResolvedWorkspaceId => WorkspaceId ?? WorkspaceIdSnake;
        public JsonElement? ResolvedOldValue => IsPresent(OldValue) ? OldValue : OldValueSnake;
        public JsonElement? ResolvedNewValue => IsPresent(NewValue) ? NewValue : NewValueSnake;

        private static bool IsPresent(JsonElement? value) =>
            value is { ValueKind: not JsonValueKind.Undefined and not JsonValueKind.Null };
    }

    private sealed class FileEventMessage
    {
        [JsonPropertyName("eventType")]
        public string? EventType { get; set; }

        [JsonPropertyName("fileId")]
        public string? FileId { get; set; }

        [JsonPropertyName("ownerId")]
        public string? OwnerId { get; set; }

        [JsonPropertyName("sharedWithUserId")]
        public string? SharedWithUserId { get; set; }

        [JsonPropertyName("timestamp")]
        public DateTime? Timestamp { get; set; }
    }
}
