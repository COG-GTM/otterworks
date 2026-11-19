using System;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;

namespace OtterWorks.Desktop.Services
{
    /// <summary>
    /// System.Text.Json settings that read and write JSON the way the client's former
    /// Newtonsoft.Json defaults did, so request bodies, persisted sessions, appsettings.json
    /// and on-screen error text stay the same.
    /// </summary>
    internal static class AppJson
    {
        public static readonly JsonSerializerOptions Options = new JsonSerializerOptions
        {
            PropertyNameCaseInsensitive = true,
            NumberHandling = JsonNumberHandling.AllowReadingFromString,
            ReadCommentHandling = JsonCommentHandling.Skip,
            AllowTrailingCommas = true,
            Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        };

        public static readonly JsonDocumentOptions DocumentOptions = new JsonDocumentOptions
        {
            CommentHandling = JsonCommentHandling.Skip,
            AllowTrailingCommas = true,
        };

        // Newtonsoft wrote characters outside the Basic Multilingual Plane (emoji) as-is;
        // System.Text.Json always escapes them as \uD83D\uDE00 pairs.
        private static readonly Regex EscapedSurrogatePair = new Regex(
            @"(?<!\\)((?:\\\\)*)\\u(D[89AB][0-9A-F]{2})\\u(D[C-F][0-9A-F]{2})",
            RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);

        public static string Serialize(object value, Type type)
        {
            return UnescapeSurrogatePairs(JsonSerializer.Serialize(value, type, Options));
        }

        /// <summary>Formats a JSON value as Newtonsoft's <c>JToken.ToString()</c> did.</summary>
        public static string ToDisplayString(JsonElement value)
        {
            switch (value.ValueKind)
            {
                case JsonValueKind.String:
                    return value.GetString();
                case JsonValueKind.True:
                    return bool.TrueString;
                case JsonValueKind.False:
                    return bool.FalseString;
                case JsonValueKind.Number:
                    long integer;
                    return value.TryGetInt64(out integer)
                        ? integer.ToString(CultureInfo.CurrentCulture)
                        : value.GetDouble().ToString(CultureInfo.CurrentCulture);
                case JsonValueKind.Null:
                case JsonValueKind.Undefined:
                    return string.Empty;
                default:
                    using (var stream = new MemoryStream())
                    {
                        var writerOptions = new JsonWriterOptions { Indented = true, Encoder = Options.Encoder };
                        using (var writer = new Utf8JsonWriter(stream, writerOptions))
                        {
                            value.WriteTo(writer);
                        }

                        return UnescapeSurrogatePairs(Encoding.UTF8.GetString(stream.ToArray()));
                    }
            }
        }

        private static string UnescapeSurrogatePairs(string json)
        {
            return EscapedSurrogatePair.Replace(json, m =>
                m.Groups[1].Value
                + (char)Convert.ToInt32(m.Groups[2].Value, 16)
                + (char)Convert.ToInt32(m.Groups[3].Value, 16));
        }
    }
}
