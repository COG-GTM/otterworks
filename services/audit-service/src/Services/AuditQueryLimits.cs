namespace OtterWorks.AuditService.Services;

public static class AuditQueryLimits
{
    public const int DefaultWindowDays = 30;
    public const int MaxRangeDays = 90;
    public const int MaxPageOffset = 1000;
    public const int MaxCallsPerPage = 50;
    public const int MaxCallsPerCollection = 500;
    public const int MaxItemsPerCall = 1000;
    public const int MaxReportEvents = 10_000;
    public const int MaxExportEvents = 10_000;
    public const int MaxArchiveEventsPerRun = 10_000;

    public static void EnsureRange(DateTime from, DateTime to)
    {
        if (from > to)
            throw new AuditQueryException("'from' must not be after 'to'.");

        if (to - from > TimeSpan.FromDays(MaxRangeDays))
            throw new AuditQueryException($"Date range must not exceed {MaxRangeDays} days.");
    }
}

public class AuditQueryException : Exception
{
    public AuditQueryException(string message)
        : base(message)
    {
    }
}
