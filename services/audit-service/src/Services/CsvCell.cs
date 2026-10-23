namespace OtterWorks.AuditService.Services;

/// <summary>
/// Formats a value as a quoted CSV cell that spreadsheet applications treat as literal text.
/// Quoting alone does not stop Excel/LibreOffice from evaluating a cell that starts with a
/// formula trigger, so such values are prefixed with a single quote (OWASP CSV injection guidance).
/// </summary>
public static class CsvCell
{
    private static readonly char[] FormulaTriggers = { '=', '+', '-', '@', '\t', '\r', '\n' };

    public static string Format(string? value) => $"\"{Neutralize(value).Replace("\"", "\"\"")}\"";

    public static string Neutralize(string? value)
    {
        if (string.IsNullOrEmpty(value))
        {
            return string.Empty;
        }

        return Array.IndexOf(FormulaTriggers, value[0]) >= 0 ? "'" + value : value;
    }
}
