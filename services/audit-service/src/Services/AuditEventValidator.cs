using OtterWorks.AuditService.Config;
using OtterWorks.AuditService.Models;

namespace OtterWorks.AuditService.Services;

public static class AuditEventValidator
{
    public static string? Validate(AuditEventRequest request, AuditLimits limits)
    {
        if (string.IsNullOrWhiteSpace(request.UserId) ||
            string.IsNullOrWhiteSpace(request.Action) ||
            string.IsNullOrWhiteSpace(request.ResourceType) ||
            string.IsNullOrWhiteSpace(request.ResourceId))
        {
            return "UserId, Action, ResourceType, and ResourceId are required.";
        }

        if (request.UserId.Length > limits.MaxFieldLength ||
            request.Action.Length > limits.MaxFieldLength ||
            request.ResourceType.Length > limits.MaxFieldLength ||
            request.ResourceId.Length > limits.MaxFieldLength)
        {
            return $"UserId, Action, ResourceType, and ResourceId must be at most {limits.MaxFieldLength} characters.";
        }

        if (request.IpAddress?.Length > limits.MaxIpAddressLength)
            return $"IpAddress must be at most {limits.MaxIpAddressLength} characters.";

        if (request.UserAgent?.Length > limits.MaxUserAgentLength)
            return $"UserAgent must be at most {limits.MaxUserAgentLength} characters.";

        if (request.Details is null)
            return null;

        if (request.Details.Count > limits.MaxDetailsEntries)
            return $"Details may contain at most {limits.MaxDetailsEntries} entries.";

        var total = 0;
        foreach (var (key, value) in request.Details)
        {
            if (key.Length > limits.MaxDetailKeyLength)
                return $"Details keys must be at most {limits.MaxDetailKeyLength} characters.";
            if (value?.Length > limits.MaxDetailValueLength)
                return $"Details values must be at most {limits.MaxDetailValueLength} characters.";
            total += key.Length + (value?.Length ?? 0);
        }

        if (total > limits.MaxDetailsTotalLength)
            return $"Details must be at most {limits.MaxDetailsTotalLength} characters in total.";

        return null;
    }

    // Events from the internal SNS feed cannot be rejected back to a caller, so oversized
    // fields are truncated and excess Details entries are dropped instead.
    public static void Normalize(AuditEvent auditEvent, AuditLimits limits)
    {
        auditEvent.UserId = Truncate(auditEvent.UserId, limits.MaxFieldLength)!;
        auditEvent.Action = Truncate(auditEvent.Action, limits.MaxFieldLength)!;
        auditEvent.ResourceType = Truncate(auditEvent.ResourceType, limits.MaxFieldLength)!;
        auditEvent.ResourceId = Truncate(auditEvent.ResourceId, limits.MaxFieldLength)!;
        auditEvent.IpAddress = Truncate(auditEvent.IpAddress, limits.MaxIpAddressLength);
        auditEvent.UserAgent = Truncate(auditEvent.UserAgent, limits.MaxUserAgentLength);

        if (auditEvent.Details is null)
            return;

        var details = new Dictionary<string, string>();
        var total = 0;
        foreach (var (key, value) in auditEvent.Details)
        {
            if (details.Count >= limits.MaxDetailsEntries || key.Length > limits.MaxDetailKeyLength)
                continue;
            var truncated = Truncate(value, limits.MaxDetailValueLength) ?? string.Empty;
            if (total + key.Length + truncated.Length > limits.MaxDetailsTotalLength)
                continue;
            total += key.Length + truncated.Length;
            details[key] = truncated;
        }

        auditEvent.Details = details;
    }

    private static string? Truncate(string? value, int maxLength) =>
        value is not null && value.Length > maxLength ? value[..maxLength] : value;
}
