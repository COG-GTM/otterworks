using System.Globalization;
using System.Text;

namespace OtterWorks.AuditService.Services;

public static class AuditCsvWriter
{
    public static readonly string[] Columns =
    {
        "Id", "Timestamp", "UserId", "Action", "ResourceType", "ResourceId", "IpAddress", "UserAgent",
        "WorkspaceId", "OldValue", "NewValue", "EventTimestamp",
    };

    private static readonly string[] WorkspaceKeys = { "workspace_id", "workspaceId" };
    private static readonly string[] OldValueKeys = { "old_value", "oldValue" };
    private static readonly string[] NewValueKeys = { "new_value", "newValue" };
    private static readonly string[] EventTimestampKeys = { "timestamp" };

    private static readonly char[] FormulaPrefixes = { '=', '+', '-', '@', '\t', '\r' };

    public static string Write(IEnumerable<AuditEvent> events)
    {
        var sb = new StringBuilder();
        sb.AppendLine(string.Join(',', Columns));

        foreach (var e in events)
        {
            var fields = new[]
            {
                e.Id,
                e.Timestamp.ToString("O", CultureInfo.InvariantCulture),
                e.UserId,
                e.Action,
                e.ResourceType,
                e.ResourceId,
                e.IpAddress,
                e.UserAgent,
                Detail(e, WorkspaceKeys),
                Detail(e, OldValueKeys),
                Detail(e, NewValueKeys),
                Detail(e, EventTimestampKeys),
            };

            sb.AppendLine(string.Join(',', fields.Select(Field)));
        }

        return sb.ToString();
    }

    public static string Field(string? value)
    {
        if (string.IsNullOrEmpty(value))
            return "\"\"";

        var safe = NeedsFormulaGuard(value) ? "'" + value : value;
        return "\"" + safe.Replace("\"", "\"\"") + "\"";
    }

    private static bool NeedsFormulaGuard(string value)
    {
        var trimmed = value.TrimStart();
        var startsLikeFormula = Array.IndexOf(FormulaPrefixes, value[0]) >= 0 ||
            (trimmed.Length > 0 && Array.IndexOf(FormulaPrefixes, trimmed[0]) >= 0);

        return startsLikeFormula &&
            !double.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out _);
    }

    private static string? Detail(AuditEvent e, string[] keys)
    {
        if (e.Details is null)
            return null;

        foreach (var key in keys)
        {
            if (e.Details.TryGetValue(key, out var value))
                return value;
        }

        return null;
    }
}
