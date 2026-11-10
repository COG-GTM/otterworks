using System.Text.RegularExpressions;
using OtterWorks.AuditService.Models;

namespace OtterWorks.AuditService.Services;

/// <summary>
/// Audit event contract v2. Mirrors docs/audit-events.md and docs/schemas/audit-event.v2.schema.json.
/// </summary>
public static partial class AuditContract
{
    public const string ActionPattern = @"^[a-z]+(\.[a-z_]+)+$";
    public const string RedactedValue = "[REDACTED]";

    public static readonly string[] RequiredFields = { "userId", "action", "resourceType", "outcome", "serviceName" };
    public static readonly string[] Outcomes = { "success", "failure", "denied" };
    public static readonly string[] ActorTypes = { "user", "admin", "service", "anonymous" };

    // The epic's common actions include the single-word `export` and `delete`, which the
    // dot-namespaced pattern alone would reject.
    public static readonly string[] SingleWordActions = { "export", "delete" };

    [GeneratedRegex(ActionPattern)]
    private static partial Regex ActionRegex();

    [GeneratedRegex("(password|passwd|secret|token|credential|authorization|cookie|api[_-]?key|private[_-]?key)", RegexOptions.IgnoreCase)]
    private static partial Regex SensitiveKeyRegex();

    public static bool IsValidAction(string? action) =>
        !string.IsNullOrWhiteSpace(action) && (ActionRegex().IsMatch(action) || SingleWordActions.Contains(action));

    public static List<string> Validate(AuditEventRequest request)
    {
        var errors = new List<string>();

        if (string.IsNullOrWhiteSpace(request.UserId))
            errors.Add("userId (actor) is required; use \"anonymous\" when there is no authenticated actor.");

        if (string.IsNullOrWhiteSpace(request.Action))
            errors.Add("action is required.");
        else if (!IsValidAction(request.Action))
            errors.Add($"action '{request.Action}' is not in the audit taxonomy; it must match {ActionPattern} (or be 'export'/'delete').");

        if (string.IsNullOrWhiteSpace(request.ResourceType))
            errors.Add("resourceType is required.");

        if (string.IsNullOrWhiteSpace(request.Outcome))
            errors.Add("outcome is required.");
        else if (!Outcomes.Contains(request.Outcome))
            errors.Add($"outcome must be one of: {string.Join(", ", Outcomes)}.");

        if (string.IsNullOrWhiteSpace(request.ServiceName))
            errors.Add("serviceName is required.");

        if (!string.IsNullOrEmpty(request.ActorType) && !ActorTypes.Contains(request.ActorType))
            errors.Add($"actorType must be one of: {string.Join(", ", ActorTypes)}.");

        return errors;
    }

    /// <summary>
    /// Defence in depth: emitters must never send secrets, but if a detail key looks like one,
    /// its value is replaced so it never reaches DynamoDB or S3.
    /// </summary>
    public static Dictionary<string, string>? RedactDetails(Dictionary<string, string>? details)
    {
        if (details is null)
            return null;

        return details.ToDictionary(
            kvp => kvp.Key,
            kvp => SensitiveKeyRegex().IsMatch(kvp.Key) ? RedactedValue : kvp.Value);
    }

    public static AuditEvent ToEntity(AuditEventRequest request) => new()
    {
        Id = Guid.NewGuid().ToString(),
        UserId = request.UserId,
        ActorEmail = NullIfEmpty(request.ActorEmail),
        ActorType = NullIfEmpty(request.ActorType),
        TenantId = NullIfEmpty(request.TenantId),
        Action = request.Action,
        ResourceType = request.ResourceType,
        ResourceId = request.ResourceId ?? string.Empty,
        Outcome = NullIfEmpty(request.Outcome),
        Details = RedactDetails(request.Details),
        IpAddress = NullIfEmpty(request.IpAddress) ?? NullIfEmpty(request.SourceIp),
        UserAgent = NullIfEmpty(request.UserAgent),
        RequestId = NullIfEmpty(request.RequestId),
        ServiceName = NullIfEmpty(request.ServiceName),
        Timestamp = request.Timestamp?.ToUniversalTime() ?? DateTime.UtcNow,
    };

    private static string? NullIfEmpty(string? value) => string.IsNullOrWhiteSpace(value) ? null : value;
}
