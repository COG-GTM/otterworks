namespace OtterWorks.AuditService.Services;

public interface IResourceAccessAuthorizer
{
    /// <summary>
    /// Whether <paramref name="userId"/> may read the audit history of
    /// <paramref name="resourceId"/>. File history is readable by the owner
    /// and by users the file is shared with; resources that are not files
    /// are not restricted here.
    /// </summary>
    Task<bool> CanReadHistoryAsync(string resourceId, string? userId, CancellationToken ct = default);
}
