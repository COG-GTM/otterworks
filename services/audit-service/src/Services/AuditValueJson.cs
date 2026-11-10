using System.Text.Encodings.Web;
using System.Text.Json;

namespace OtterWorks.AuditService.Services;

public static class AuditValueJson
{
    private static readonly JsonSerializerOptions CompactOptions = new()
    {
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
    };

    public static JsonElement? Normalize(JsonElement? value) =>
        value is { ValueKind: not (JsonValueKind.Undefined or JsonValueKind.Null) } element
            ? element.Clone()
            : null;

    public static string? ToCompactString(JsonElement? value) =>
        Normalize(value) is { } element ? JsonSerializer.Serialize(element, CompactOptions) : null;

    public static JsonElement? Parse(string? json)
    {
        if (string.IsNullOrEmpty(json))
            return null;

        try
        {
            using var doc = JsonDocument.Parse(json);
            return Normalize(doc.RootElement);
        }
        catch (JsonException)
        {
            return JsonSerializer.SerializeToElement(json);
        }
    }
}
