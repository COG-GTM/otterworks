using System.Text;
using System.Text.Json;

namespace OtterWorks.AuditService.Services;

/// <summary>
/// Writes audit events as RFC 4180 CSV. Columns and cell values are derived from the
/// JSON serialization of <see cref="AuditEvent"/>, so the CSV export always carries the
/// same fields, in the same order, as the JSON export.
/// </summary>
public static class AuditCsvWriter
{
    public const string ContentType = "text/csv; charset=utf-8";

    private const string RecordSeparator = "\r\n";

    public static string Write(IEnumerable<AuditEvent> events, JsonSerializerOptions jsonOptions)
    {
        var cellOptions = new JsonSerializerOptions(jsonOptions) { WriteIndented = false };
        var columns = GetColumns(cellOptions);

        var sb = new StringBuilder();
        AppendRecord(sb, columns);

        foreach (var auditEvent in events)
        {
            var json = JsonSerializer.SerializeToElement(auditEvent, cellOptions);
            AppendRecord(sb, columns.Select(column =>
                json.TryGetProperty(column, out var value) ? ToCell(value) : string.Empty));
        }

        return sb.ToString();
    }

    public static string EscapeField(string value)
    {
        if (value.IndexOfAny(['"', ',', '\r', '\n']) < 0)
        {
            return value;
        }

        return $"\"{value.Replace("\"", "\"\"")}\"";
    }

    private static List<string> GetColumns(JsonSerializerOptions options) =>
        JsonSerializer.SerializeToElement(new AuditEvent(), options)
            .EnumerateObject()
            .Select(p => p.Name)
            .ToList();

    private static string ToCell(JsonElement value) => value.ValueKind switch
    {
        JsonValueKind.Null or JsonValueKind.Undefined => string.Empty,
        JsonValueKind.String => value.GetString() ?? string.Empty,
        _ => value.GetRawText(),
    };

    private static void AppendRecord(StringBuilder sb, IEnumerable<string> fields)
    {
        sb.AppendJoin(',', fields.Select(EscapeField));
        sb.Append(RecordSeparator);
    }
}
