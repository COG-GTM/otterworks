using System.Security.Claims;
using OtterWorks.AuditService.Auth;
using OtterWorks.AuditService.Models;
using OtterWorks.AuditService.Services;

namespace OtterWorks.AuditService.Controllers;

public static class AuditController
{
    public static void MapAuditEndpoints(this WebApplication app)
    {
        // Non-admin callers only ever see their own events; compliance, export and archive are admin-only.
        var group = app.MapGroup("/api/v1/audit").RequireAuthorization();

        group.MapPost("/events", RecordEvent)
            .WithName("RecordAuditEvent")
            .Produces<AuditEventResponse>(StatusCodes.Status201Created)
            .Produces(StatusCodes.Status400BadRequest);

        group.MapGet("/events", QueryEvents)
            .WithName("QueryAuditEvents")
            .Produces<AuditEventPage>(StatusCodes.Status200OK);

        group.MapGet("/events/{id}", GetEvent)
            .WithName("GetAuditEvent")
            .Produces<AuditEventResponse>(StatusCodes.Status200OK)
            .Produces(StatusCodes.Status404NotFound);

        group.MapGet("/reports/user/{userId}", GetUserActivityReport)
            .WithName("GetUserActivityReport")
            .Produces<UserActivityReport>(StatusCodes.Status200OK);

        group.MapGet("/resources/{resourceId}/history", GetResourceHistory)
            .WithName("GetResourceHistory")
            .Produces<ResourceHistory>(StatusCodes.Status200OK);

        group.MapGet("/reports/compliance", GetComplianceReport)
            .WithName("GetComplianceReport")
            .RequireAuthorization(AuditAuthentication.AdminPolicy)
            .Produces<ComplianceReport>(StatusCodes.Status200OK);

        group.MapGet("/export", ExportAuditLog)
            .WithName("ExportAuditLog")
            .RequireAuthorization(AuditAuthentication.AdminPolicy)
            .Produces<ExportResult>(StatusCodes.Status200OK);

        group.MapPost("/archive", ArchiveOldEvents)
            .WithName("ArchiveOldEvents")
            .RequireAuthorization(AuditAuthentication.AdminPolicy)
            .Produces<ArchiveResult>(StatusCodes.Status200OK);
    }

    private static async Task<IResult> RecordEvent(
        AuditEventRequest request,
        ClaimsPrincipal user,
        HttpContext httpContext,
        IAuditService auditService)
    {
        if (string.IsNullOrWhiteSpace(request.Action) ||
            string.IsNullOrWhiteSpace(request.ResourceType) ||
            string.IsNullOrWhiteSpace(request.ResourceId))
        {
            return Results.BadRequest(new { error = "Action, ResourceType, and ResourceId are required." });
        }

        // The actor and client metadata come from the verified request, never the body.
        request.UserId = user.GetUserId()!;
        request.IpAddress = GetClientIp(httpContext);
        request.UserAgent = httpContext.Request.Headers.UserAgent.ToString() is { Length: > 0 } ua ? ua : null;

        var response = await auditService.RecordEventAsync(request);
        return Results.Created($"/api/v1/audit/events/{response.Id}", response);
    }

    private static async Task<IResult> QueryEvents(
        string? user_id,
        string? action,
        string? resource,
        string? resource_type,
        DateTime? from,
        DateTime? to,
        int? page,
        int? size,
        ClaimsPrincipal user,
        IAuditService auditService)
    {
        var pageNumber = page ?? 1;
        var pageSize = Math.Clamp(size ?? 20, 1, 100);

        var userFilter = user_id;
        if (!user.IsAuditAdmin())
        {
            var callerId = user.GetUserId()!;
            if (!string.IsNullOrEmpty(user_id) && user_id != callerId)
            {
                return Results.Forbid();
            }
            userFilter = callerId;
        }

        var result = await auditService.QueryEventsAsync(userFilter, action, resource_type, resource, from, to, pageNumber, pageSize);
        return Results.Ok(result);
    }

    private static async Task<IResult> GetEvent(
        string id,
        ClaimsPrincipal user,
        IAuditService auditService)
    {
        var result = await auditService.GetEventAsync(id);
        if (result is null || (!user.IsAuditAdmin() && result.UserId != user.GetUserId()))
        {
            return Results.NotFound(new { error = "Event not found." });
        }
        return Results.Ok(result);
    }

    private static async Task<IResult> GetUserActivityReport(
        string userId,
        string? period,
        ClaimsPrincipal user,
        IAuditService auditService)
    {
        if (!user.IsAuditAdmin() && userId != user.GetUserId())
        {
            return Results.Forbid();
        }

        var reportPeriod = period ?? "30d";
        var report = await auditService.GetUserActivityReportAsync(userId, reportPeriod);
        return Results.Ok(report);
    }

    private static async Task<IResult> GetResourceHistory(
        string resourceId,
        ClaimsPrincipal user,
        IAuditService auditService)
    {
        var restrictTo = user.IsAuditAdmin() ? null : user.GetUserId();
        var history = await auditService.GetResourceHistoryAsync(resourceId, restrictTo);
        return Results.Ok(history);
    }

    private static async Task<IResult> GetComplianceReport(
        string? period,
        IAuditService auditService)
    {
        var reportPeriod = period ?? "30d";
        var report = await auditService.GetComplianceReportAsync(reportPeriod);
        return Results.Ok(report);
    }

    private static async Task<IResult> ExportAuditLog(
        string? format,
        DateTime? from,
        DateTime? to,
        IAuditService auditService)
    {
        var exportFormat = format ?? "json";
        var exportFrom = from ?? DateTime.UtcNow.AddDays(-30);
        var exportTo = to ?? DateTime.UtcNow;

        if (!string.Equals(exportFormat, "csv", StringComparison.OrdinalIgnoreCase) &&
            !string.Equals(exportFormat, "json", StringComparison.OrdinalIgnoreCase))
        {
            return Results.BadRequest(new { error = "Format must be 'csv' or 'json'." });
        }

        var result = await auditService.ExportAsync(exportFrom, exportTo, exportFormat);
        return Results.Ok(result);
    }

    private static async Task<IResult> ArchiveOldEvents(
        IAuditService auditService)
    {
        var result = await auditService.ArchiveOldEventsAsync();
        return Results.Ok(result);
    }

    // Best-effort client address. The last X-Forwarded-For entry is the one set by the
    // closest proxy (ingress-nginx in tenants); the api-gateway passes it through as-is.
    private static string? GetClientIp(HttpContext httpContext)
    {
        var forwarded = httpContext.Request.Headers["X-Forwarded-For"].ToString();
        if (!string.IsNullOrWhiteSpace(forwarded))
        {
            var last = forwarded.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).LastOrDefault();
            if (!string.IsNullOrEmpty(last))
            {
                return last;
            }
        }
        return httpContext.Connection.RemoteIpAddress?.ToString();
    }
}
