namespace OtterWorks.AuditService.Services;

public enum ResourceAccessDecision
{
    /// <summary>The caller may read the resource's history.</summary>
    Allow,

    /// <summary>The caller may not read the resource's history.</summary>
    Deny,

    /// <summary>
    /// file-service does not know the resource, so the file rule cannot decide:
    /// either a non-file resource or a file that no longer exists.
    /// </summary>
    Unknown,
}

public interface IResourceAccessAuthorizer
{
    /// <summary>
    /// Whether <paramref name="userId"/> may read the audit history of
    /// <paramref name="resourceId"/>. File history is readable by the owner
    /// and by users the file is shared with.
    /// </summary>
    Task<ResourceAccessDecision> EvaluateAsync(string resourceId, string? userId, CancellationToken ct = default);
}
