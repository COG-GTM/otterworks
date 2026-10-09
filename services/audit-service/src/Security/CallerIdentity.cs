namespace OtterWorks.AuditService.Security;

/// <summary>
/// Identity of the end user as asserted by the API gateway, which strips any
/// client-supplied X-User-* headers and re-derives them from the validated JWT.
/// </summary>
public sealed class CallerIdentity
{
    public const string UserIdHeader = "X-User-ID";
    public const string RolesHeader = "X-User-Roles";
    public const string AdminRole = "ADMIN";

    private CallerIdentity(string userId, IReadOnlySet<string> roles)
    {
        UserId = userId;
        Roles = roles;
    }

    public string UserId { get; }

    public IReadOnlySet<string> Roles { get; }

    public bool IsAdmin => Roles.Contains(AdminRole);

    public static CallerIdentity? FromRequest(HttpRequest request)
    {
        var userId = request.Headers[UserIdHeader].ToString().Trim();
        if (string.IsNullOrEmpty(userId))
            return null;

        var roles = request.Headers[RolesHeader].ToString()
            .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .ToHashSet(StringComparer.OrdinalIgnoreCase);

        return new CallerIdentity(userId, roles);
    }

    /// <summary>
    /// The client address as seen by the nearest proxy: the right-most
    /// X-Forwarded-For entry (appended by the gateway), else the TCP peer.
    /// Left-most entries are client-controlled and are never used.
    /// </summary>
    public static string? ClientIpAddress(HttpContext context)
    {
        var forwarded = context.Request.Headers["X-Forwarded-For"].ToString();
        if (!string.IsNullOrWhiteSpace(forwarded))
        {
            var last = forwarded.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
                .LastOrDefault();
            if (!string.IsNullOrEmpty(last) && System.Net.IPAddress.TryParse(last, out var parsed))
                return parsed.ToString();
        }

        return context.Connection.RemoteIpAddress?.ToString();
    }
}
