using System.Security.Claims;
using OtterWorks.AuditService.Auth;
using OtterWorks.AuditService.Models;
using OtterWorks.AuditService.Services;

namespace OtterWorks.AuditService.Controllers;

public static class AuditController
{
    public static void MapAuditEndpoints(this WebApplication app)
    {
        var group = app.MapGroup("/api/v1/audit")
            .RequireAuthorization(AuditAuthentication.CallerPolicy);

        group.MapPost("/events", RecordEvent)
            .WithName("RecordAuditEvent")
            .Produces<AuditEventResponse>(StatusCodes.Status201Created)
            .Produces(StatusCodes.Status400BadRequest)
            .Produces(StatusCodes.Status403Forbidden);

        group.MapGet("/events", QueryEvents)
            .WithName("QueryAuditEvents")
            .Produces<AuditEventPage>(StatusCodes.Status200OK)
            .Produces(StatusCodes.Status403Forbidden);

        group.MapGet("/events/{id}", GetEvent)
            .WithName("GetAuditEvent")
            .Produces<AuditEventResponse>(StatusCodes.Status200OK)
            .Produces(StatusCodes.Status404NotFound);

        group.MapGet("/reports/user/{userId}", GetUserActivityReport)
            .WithName("GetUserActivityReport")
            .Produces<UserActivityReport>(StatusCodes.Status200OK)
            .Produces(StatusCodes.Status403Forbidden);

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
        IAuditService auditService)
    {
        if (string.IsNullOrWhiteSpace(request.Action) ||
            string.IsNullOrWhiteSpace(request.ResourceType) ||
            string.IsNullOrWhiteSpace(request.ResourceId))
        {
            return Results.BadRequest(new { error = "Action, ResourceType, and ResourceId are required." });
        }

        // Events are always attributed to the authenticated caller, never to a body-supplied user.
        var callerId = user.UserId();
        if (!string.IsNullOrWhiteSpace(request.UserId) && request.UserId != callerId)
        {
            return Forbidden("Audit events can only be recorded for the authenticated user.");
        }

        request.UserId = callerId;

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
        if (!user.IsAdmin())
        {
            if (!string.IsNullOrEmpty(user_id) && user_id != user.UserId())
            {
                return Forbidden("Only administrators can query other users' audit events.");
            }

            user_id = user.UserId();
        }

        var pageNumber = page ?? 1;
        var pageSize = Math.Clamp(size ?? 20, 1, 100);

        var result = await auditService.QueryEventsAsync(user_id, action, resource_type, resource, from, to, pageNumber, pageSize);
        return Results.Ok(result);
    }

    private static async Task<IResult> GetEvent(
        string id,
        ClaimsPrincipal user,
        IAuditService auditService)
    {
        var result = await auditService.GetEventAsync(id);
        if (result is null || (!user.IsAdmin() && result.UserId != user.UserId()))
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
        if (!user.IsAdmin() && userId != user.UserId())
        {
            return Forbidden("Only administrators can view other users' activity reports.");
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
        var history = await auditService.GetResourceHistoryAsync(resourceId);
        if (!user.IsAdmin())
        {
            var callerId = user.UserId();
            history.Events = history.Events.Where(e => e.UserId == callerId).ToList();
            history.TotalEvents = history.Events.Count;
        }

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

    private static IResult Forbidden(string message) =>
        Results.Json(new { error = message }, statusCode: StatusCodes.Status403Forbidden);
}
