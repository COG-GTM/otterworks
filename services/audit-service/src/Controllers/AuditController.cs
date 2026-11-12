using OtterWorks.AuditService.Auth;
using OtterWorks.AuditService.Models;
using OtterWorks.AuditService.Services;

namespace OtterWorks.AuditService.Controllers;

public static class AuditController
{
    public static void MapAuditEndpoints(this WebApplication app)
    {
        var group = app.MapGroup("/api/v1/audit").RequireCaller();

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
            .RequireAdmin()
            .WithName("GetComplianceReport")
            .Produces<ComplianceReport>(StatusCodes.Status200OK)
            .Produces(StatusCodes.Status403Forbidden);

        group.MapGet("/export", ExportAuditLog)
            .RequireAdmin()
            .WithName("ExportAuditLog")
            .Produces<ExportResult>(StatusCodes.Status200OK)
            .Produces(StatusCodes.Status403Forbidden);

        group.MapPost("/archive", ArchiveOldEvents)
            .RequireAdmin()
            .WithName("ArchiveOldEvents")
            .Produces<ArchiveResult>(StatusCodes.Status200OK)
            .Produces(StatusCodes.Status403Forbidden);
    }

    private static IResult Forbidden(string message) =>
        Results.Json(new { error = message }, statusCode: StatusCodes.Status403Forbidden);

    private static async Task<IResult> RecordEvent(
        AuditEventRequest request,
        HttpContext httpContext,
        IAuditService auditService)
    {
        var caller = CallerIdentity.Get(httpContext);

        if (string.IsNullOrWhiteSpace(request.Action) ||
            string.IsNullOrWhiteSpace(request.ResourceType) ||
            string.IsNullOrWhiteSpace(request.ResourceId))
        {
            return Results.BadRequest(new { error = "Action, ResourceType, and ResourceId are required." });
        }

        // The actor is always the authenticated caller; events cannot be recorded in another user's name.
        if (!string.IsNullOrWhiteSpace(request.UserId) &&
            !string.Equals(request.UserId, caller.UserId, StringComparison.Ordinal))
        {
            return Forbidden("UserId must match the authenticated caller.");
        }

        request.UserId = caller.UserId;

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
        HttpContext httpContext,
        IAuditService auditService)
    {
        var caller = CallerIdentity.Get(httpContext);
        if (!caller.IsAdmin)
        {
            if (user_id is not null && !caller.CanAccessUser(user_id))
                return Forbidden("You may only query your own audit events.");
            user_id = caller.UserId;
        }

        var pageNumber = page ?? 1;
        var pageSize = Math.Clamp(size ?? 20, 1, 100);

        var result = await auditService.QueryEventsAsync(user_id, action, resource_type, resource, from, to, pageNumber, pageSize);
        return Results.Ok(result);
    }

    private static async Task<IResult> GetEvent(
        string id,
        HttpContext httpContext,
        IAuditService auditService)
    {
        var result = await auditService.GetEventAsync(id);
        // Another user's event is reported as missing so event ids cannot be probed.
        return result is not null && CallerIdentity.Get(httpContext).CanAccessUser(result.UserId)
            ? Results.Ok(result)
            : Results.NotFound(new { error = "Event not found." });
    }

    private static async Task<IResult> GetUserActivityReport(
        string userId,
        string? period,
        HttpContext httpContext,
        IAuditService auditService)
    {
        if (!CallerIdentity.Get(httpContext).CanAccessUser(userId))
            return Forbidden("You may only view your own activity report.");

        var reportPeriod = period ?? "30d";
        var report = await auditService.GetUserActivityReportAsync(userId, reportPeriod);
        return Results.Ok(report);
    }

    private static async Task<IResult> GetResourceHistory(
        string resourceId,
        HttpContext httpContext,
        IAuditService auditService)
    {
        var caller = CallerIdentity.Get(httpContext);
        var history = await auditService.GetResourceHistoryAsync(resourceId);
        if (!caller.IsAdmin)
        {
            history.Events = history.Events.Where(e => caller.CanAccessUser(e.UserId)).ToList();
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
}
