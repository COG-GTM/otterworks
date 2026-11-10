using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Authorization.Policy;
using OtterWorks.AuditService.Services;

namespace OtterWorks.AuditService.Auth;

/// <summary>Audits denied (401/403) calls to self-audited endpoints before the default response is written.</summary>
public sealed class DeniedAuditResultHandler : IAuthorizationMiddlewareResultHandler
{
    private readonly AuthorizationMiddlewareResultHandler _default = new();
    private readonly SelfAuditor _selfAuditor;

    public DeniedAuditResultHandler(SelfAuditor selfAuditor)
    {
        _selfAuditor = selfAuditor;
    }

    public async Task HandleAsync(
        RequestDelegate next,
        HttpContext context,
        AuthorizationPolicy policy,
        PolicyAuthorizationResult authorizeResult)
    {
        var metadata = context.GetEndpoint()?.Metadata.GetMetadata<SelfAuditMetadata>();
        if (metadata is not null && (authorizeResult.Challenged || authorizeResult.Forbidden))
        {
            var resourceId = metadata.ResourceRouteValue is not null
                ? context.Request.RouteValues[metadata.ResourceRouteValue]?.ToString() ?? string.Empty
                : string.Empty;
            await _selfAuditor.RecordAsync(context, metadata.Action, metadata.ResourceType, resourceId, "denied",
                new Dictionary<string, string>
                {
                    ["reason"] = authorizeResult.Forbidden ? "not_admin" : "unauthenticated",
                    ["path"] = context.Request.Path.ToString(),
                });
        }

        await _default.HandleAsync(next, context, policy, authorizeResult);
    }
}
