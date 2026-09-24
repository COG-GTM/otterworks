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
            if (fileEvent?.EventType is not null && FileEventActions.ContainsKey(fileEvent.EventType))
            {
                var fileAuditEvent = ToAuditEvent(message.MessageId, fileEvent);

                await _repository.SaveEventAsync(fileAuditEvent);
                _logger.LogDebug("Processed {EventType} SNS event for {FileId}", fileEvent.EventType, fileEvent.FileId);
                await _sqsClient.DeleteMessageAsync(_queueUrl, message.ReceiptHandle, ct);
                return;
            }

            var auditEvent = JsonSerializer.Deserialize<AuditEventMessage>(eventBody, new JsonSerializerOptions
            {
                PropertyNameCaseInsensitive = true,
            });

            if (auditEvent is null)
            {
                _logger.LogWarning("Failed to deserialize audit event from message {MessageId}", message.MessageId);
                await _sqsClient.DeleteMessageAsync(_queueUrl, message.ReceiptHandle, ct);
                return;
            }

            var entity = new AuditEvent
            {
                Id = message.MessageId,
                UserId = auditEvent.UserId ?? "system",
                Action = auditEvent.Action ?? "unknown",
                ResourceType = auditEvent.ResourceType ?? "unknown",
                ResourceId = auditEvent.ResourceId ?? string.Empty,
                Details = auditEvent.Details,
                IpAddress = auditEvent.IpAddress,
                UserAgent = auditEvent.UserAgent,
                Timestamp = auditEvent.Timestamp ?? DateTime.UtcNow,
            };

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

    /// File-service event types that become audit events on the resource
    /// timeline, mapped to the action verb stored in DynamoDB.
    private static readonly Dictionary<string, string> FileEventActions = new()
    {
        ["file_uploaded"] = "upload",
        ["file_updated"] = "update",
        ["file_moved"] = "move",
        ["file_shared"] = "share",
        ["file_unshared"] = "unshare",
        ["file_downloaded"] = "download",
        ["file_trashed"] = "trash",
        ["file_restored"] = "restore",
        ["file_deleted"] = "delete",
    };

    internal static AuditEvent ToAuditEvent(string messageId, FileEventMessage fileEvent)
    {
        var eventType = fileEvent.EventType ?? string.Empty;
        var action = FileEventActions.GetValueOrDefault(eventType, eventType);

        // A rename arrives as an update carrying the old name.
        if (action == "update" && !string.IsNullOrWhiteSpace(fileEvent.PreviousName))
        {
            action = "rename";
        }

        var details = new Dictionary<string, string>();
        AddDetail(details, "name", fileEvent.Name);
        AddDetail(details, "previousName", fileEvent.PreviousName);
        AddDetail(details, "folderId", fileEvent.FolderId);
        AddDetail(details, "folderName", fileEvent.FolderName);
        AddDetail(details, "permission", fileEvent.Permission);
        AddDetail(details, "sharedWithUserId", fileEvent.SharedWithUserId);

        return new AuditEvent
        {
            Id = messageId,
            UserId = fileEvent.ActorId ?? fileEvent.OwnerId ?? "system",
            Action = action,
            ResourceType = "file",
            ResourceId = fileEvent.FileId ?? string.Empty,
            Details = details.Count > 0 ? details : null,
            Timestamp = fileEvent.Timestamp ?? DateTime.UtcNow,
        };
    }

    private static void AddDetail(Dictionary<string, string> details, string key, string? value)
    {
        if (!string.IsNullOrWhiteSpace(value))
        {
            details[key] = value;
        }
    }

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
        public DateTime? Timestamp { get; set; }
    }

    internal sealed class FileEventMessage
    {
        [JsonPropertyName("eventType")]
        public string? EventType { get; set; }

        [JsonPropertyName("fileId")]
        public string? FileId { get; set; }

        [JsonPropertyName("ownerId")]
        public string? OwnerId { get; set; }

        [JsonPropertyName("actorId")]
        public string? ActorId { get; set; }

        [JsonPropertyName("sharedWithUserId")]
        public string? SharedWithUserId { get; set; }

        [JsonPropertyName("permission")]
        public string? Permission { get; set; }

        [JsonPropertyName("name")]
        public string? Name { get; set; }

        [JsonPropertyName("previousName")]
        public string? PreviousName { get; set; }

        [JsonPropertyName("folderId")]
        public string? FolderId { get; set; }

        [JsonPropertyName("folderName")]
        public string? FolderName { get; set; }

        [JsonPropertyName("timestamp")]
        public DateTime? Timestamp { get; set; }
    }
}
