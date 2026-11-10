using System.Text.Json;
using System.Text.Json.Serialization;

namespace OtterWorks.AuditService.Services;

/// <summary>
/// Parses SQS bodies (raw or SNS-wrapped) into audit events. Accepts the v2 contract and the
/// legacy file-service <c>file_shared</c> message until file-service migrates.
/// </summary>
public static class AuditMessageParser
{
    private static readonly JsonSerializerOptions JsonOptions = new() { PropertyNameCaseInsensitive = true };

    public static AuditEvent? Parse(string body, string messageId)
    {
        var eventBody = TryParseSnsEnvelope(body) ?? body;

        var fileEvent = JsonSerializer.Deserialize<FileEventMessage>(eventBody, JsonOptions);
        if (fileEvent?.EventType == "file_shared")
        {
            return new AuditEvent
            {
                Id = messageId,
                UserId = fileEvent.OwnerId ?? "system",
                ActorType = "user",
                Action = "share.create",
                ResourceType = "file",
                ResourceId = fileEvent.FileId ?? string.Empty,
                Outcome = "success",
                ServiceName = "file-service",
                Details = new Dictionary<string, string>
                {
                    ["sharedWithUserId"] = fileEvent.SharedWithUserId ?? string.Empty,
                    ["legacyEventType"] = "file_shared",
                },
                Timestamp = fileEvent.Timestamp?.ToUniversalTime() ?? DateTime.UtcNow,
            };
        }

        var message = JsonSerializer.Deserialize<AuditEventMessage>(eventBody, JsonOptions);
        if (message is null)
            return null;

        return new AuditEvent
        {
            Id = messageId,
            UserId = message.UserId ?? "system",
            ActorEmail = message.ActorEmail,
            ActorType = message.ActorType,
            TenantId = message.TenantId,
            Action = message.Action ?? "unknown",
            ResourceType = message.ResourceType ?? "unknown",
            ResourceId = message.ResourceId ?? string.Empty,
            Outcome = message.Outcome ?? "success",
            Details = AuditContract.RedactDetails(message.Details),
            IpAddress = message.IpAddress ?? message.SourceIp,
            UserAgent = message.UserAgent,
            RequestId = message.RequestId,
            ServiceName = message.ServiceName,
            Timestamp = message.Timestamp?.ToUniversalTime() ?? DateTime.UtcNow,
        };
    }

    private static string? TryParseSnsEnvelope(string body)
    {
        try
        {
            using var doc = JsonDocument.Parse(body);
            if (doc.RootElement.ValueKind == JsonValueKind.Object &&
                doc.RootElement.TryGetProperty("Message", out var messageElement) &&
                messageElement.ValueKind == JsonValueKind.String)
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
        public string? ActorEmail { get; set; }
        public string? ActorType { get; set; }
        public string? TenantId { get; set; }
        public string? Action { get; set; }
        public string? ResourceType { get; set; }
        public string? ResourceId { get; set; }
        public string? Outcome { get; set; }
        public Dictionary<string, string>? Details { get; set; }
        public string? IpAddress { get; set; }
        public string? SourceIp { get; set; }
        public string? UserAgent { get; set; }
        public string? RequestId { get; set; }
        public string? ServiceName { get; set; }
        public DateTime? Timestamp { get; set; }
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
