namespace OtterWorks.AuditService.Auth;

/// <summary>
/// The authenticated caller, as forwarded by the API gateway. The gateway strips any
/// client-supplied X-User-ID / X-User-Roles and re-derives both from the validated JWT.
/// </summary>
public sealed record CallerIdentity(string UserId, IReadOnlyList<string> Roles)
{
    public const string UserIdHeader = "X-User-ID";
    public const string RolesHeader = "X-User-Roles";

    // auth-service issues uppercase enum names (ADMIN, OWNER); admin-service uses super_admin.
    private static readonly HashSet<string> AdminRoles = new(StringComparer.OrdinalIgnoreCase)
    {
        "admin", "super_admin", "owner",
    };

    public bool IsAdmin => Roles.Any(AdminRoles.Contains);

    public bool CanAccessUser(string? userId) =>
        IsAdmin || string.Equals(userId, UserId, StringComparison.Ordinal);

    public static CallerIdentity? FromHeaders(IHeaderDictionary headers)
    {
        var userId = headers[UserIdHeader].ToString().Trim();
        if (string.IsNullOrEmpty(userId))
            return null;

        var roles = headers[RolesHeader]
            .SelectMany(value => (value ?? string.Empty).Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
            .ToList();

        return new CallerIdentity(userId, roles);
    }

    public static CallerIdentity Get(HttpContext context) =>
        context.Items[typeof(CallerIdentity)] as CallerIdentity
        ?? throw new InvalidOperationException("Caller identity was not resolved for this request.");
}

public static class CallerIdentityEndpointExtensions
{
    /// <summary>Rejects requests that carry no forwarded caller identity with 401.</summary>
    public static TBuilder RequireCaller<TBuilder>(this TBuilder builder)
        where TBuilder : IEndpointConventionBuilder =>
        builder.AddEndpointFilter(async (context, next) =>
        {
            var caller = CallerIdentity.FromHeaders(context.HttpContext.Request.Headers);
            if (caller is null)
                return Results.Json(new { error = "Authentication required." }, statusCode: StatusCodes.Status401Unauthorized);

            context.HttpContext.Items[typeof(CallerIdentity)] = caller;
            return await next(context);
        });

    /// <summary>Rejects callers without an admin role with 403. Must run after <see cref="RequireCaller{TBuilder}"/>.</summary>
    public static TBuilder RequireAdmin<TBuilder>(this TBuilder builder)
        where TBuilder : IEndpointConventionBuilder =>
        builder.AddEndpointFilter(async (context, next) =>
        {
            if (!CallerIdentity.Get(context.HttpContext).IsAdmin)
                return Results.Json(new { error = "Admin role required." }, statusCode: StatusCodes.Status403Forbidden);

            return await next(context);
        });
}
