using System.Text;
using System.Text.Json;
using Amazon.DynamoDBv2.Model;

namespace OtterWorks.AuditService.Services;

internal sealed class AuditCursor
{
    public string? Partition { get; set; }
    public Dictionary<string, string>? Key { get; set; }

    public static string Encode(string? partition, Dictionary<string, AttributeValue>? lastEvaluatedKey)
    {
        var cursor = new AuditCursor
        {
            Partition = partition,
            Key = lastEvaluatedKey?.ToDictionary(kvp => kvp.Key, kvp => kvp.Value.S),
        };
        var bytes = JsonSerializer.SerializeToUtf8Bytes(cursor);
        return Convert.ToBase64String(bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_');
    }

    public static AuditCursor? Decode(string? token)
    {
        if (string.IsNullOrEmpty(token))
            return null;
        if (token.Length > 2048)
            throw new ArgumentException("Invalid cursor.");

        try
        {
            var base64 = token.Replace('-', '+').Replace('_', '/');
            base64 = base64.PadRight(base64.Length + ((4 - (base64.Length % 4)) % 4), '=');
            var cursor = JsonSerializer.Deserialize<AuditCursor>(Encoding.UTF8.GetString(Convert.FromBase64String(base64)));
            if (cursor is null || (cursor.Partition is null && cursor.Key is null))
                throw new ArgumentException("Invalid cursor.");
            return cursor;
        }
        catch (Exception ex) when (ex is FormatException or JsonException)
        {
            throw new ArgumentException("Invalid cursor.", ex);
        }
    }
}
