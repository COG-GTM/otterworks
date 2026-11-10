using System.Text.Json;

namespace OtterWorks.AuditService.Services;

/// <summary>
/// Maps folder share-link and sharing policy audit events
/// (shared/events/schemas/audit-events.json) to <see cref="AuditEvent"/>.
/// Publishers wrap the event as <c>{ "event_type", "timestamp", "payload" }</c>.
/// </summary>
public static class ShareLinkAuditEventMapper
{
    public const string EventTypePrefix = "folder_share_link.";

    public static bool TryMap(string eventBody, out AuditEvent auditEvent)
    {
        auditEvent = new AuditEvent();
        try
        {
            using var doc = JsonDocument.Parse(eventBody);
            var root = doc.RootElement;
            if (root.ValueKind != JsonValueKind.Object)
            {
                return false;
            }

            var payload = root.TryGetProperty("payload", out var inner) && inner.ValueKind == JsonValueKind.Object
                ? inner
                : root;
            var eventType = GetString(payload, "eventType") ?? GetString(root, "event_type");
            if (eventType is null || !eventType.StartsWith(EventTypePrefix, StringComparison.Ordinal))
            {
                return false;
            }

            var resource = payload.TryGetProperty("resource", out var r) && r.ValueKind == JsonValueKind.Object
                ? r
                : default;
            var actor = payload.TryGetProperty("actor", out var a) && a.ValueKind == JsonValueKind.Object
                ? a
                : default;
            var workspaceId = GetString(payload, "workspaceId") ?? string.Empty;
            var resourceType = GetString(resource, "type") ?? "folder_share_link";
            var linkId = GetString(resource, "linkId");
            var folderId = GetString(resource, "folderId");

            var details = new Dictionary<string, string>
            {
                ["workspaceId"] = workspaceId,
                ["actorType"] = GetString(actor, "type") ?? "system",
                ["oldValue"] = RawJson(payload, "oldValue"),
                ["newValue"] = RawJson(payload, "newValue"),
            };
            if (folderId is not null)
            {
                details["folderId"] = folderId;
            }

            if (linkId is not null)
            {
                details["linkId"] = linkId;
            }

            auditEvent = new AuditEvent
            {
                Id = GetString(payload, "auditId") ?? string.Empty,
                UserId = GetString(actor, "id") ?? "system",
                Action = eventType,
                ResourceType = resourceType,
                ResourceId = linkId ?? GetString(resource, "workspaceId") ?? workspaceId,
                Details = details,
                Timestamp = GetTimestamp(payload) ?? GetTimestamp(root) ?? DateTime.UtcNow,
            };
            return true;
        }
        catch (JsonException)
        {
            return false;
        }
    }

    private static string? GetString(JsonElement element, string name) =>
        element.ValueKind == JsonValueKind.Object &&
        element.TryGetProperty(name, out var value) &&
        value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;

    private static string RawJson(JsonElement element, string name) =>
        element.TryGetProperty(name, out var value) ? value.GetRawText() : "null";

    private static DateTime? GetTimestamp(JsonElement element) =>
        element.TryGetProperty("timestamp", out var value) &&
        value.ValueKind == JsonValueKind.String &&
        value.TryGetDateTimeOffset(out var parsed)
            ? parsed.UtcDateTime
            : null;
}
