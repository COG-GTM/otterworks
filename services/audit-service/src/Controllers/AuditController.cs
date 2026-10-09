using OtterWorks.AuditService.Models;
using OtterWorks.AuditService.Security;
using OtterWorks.AuditService.Services;

namespace OtterWorks.AuditService.Controllers;

public static class AuditController
{
    public static void MapAuditEndpoints(this WebApplication app)
    {
        var group = app.MapGroup("/api/v1/audit");

        group.MapPost("/events", RecordEvent)
            .WithName("RecordAuditEvent")
            .Produces<AuditEventResponse>(StatusCodes.Status201Created)
            .Produces(StatusCodes.Status400BadRequest)
            .Produces(StatusCodes.Status401Unauthorized)
            .Produces(StatusCodes.Status403Forbidden);

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
            .Produces<ComplianceReport>(StatusCodes.Status200OK);

        group.MapGet("/export", ExportAuditLog)
            .WithName("ExportAuditLog")
            .Produces<ExportResult>(StatusCodes.Status200OK);

        group.MapPost("/archive", ArchiveOldEvents)
            .WithName("ArchiveOldEvents")
            .Produces<ArchiveResult>(StatusCodes.Status200OK)
            .Produces(StatusCodes.Status401Unauthorized)
            .Produces(StatusCodes.Status403Forbidden);
    }

    internal static async Task<IResult> RecordEvent(
        AuditEventRequest request,
        HttpContext httpContext,
        IAuditService auditService)
    {
        var caller = CallerIdentity.FromRequest(httpContext.Request);
        if (caller is null)
        {
            return Results.Json(new { error = "Authentication required." }, statusCode: StatusCodes.Status401Unauthorized);
        }

        if (!string.IsNullOrWhiteSpace(request.UserId) &&
            !string.Equals(request.UserId.Trim(), caller.UserId, StringComparison.Ordinal))
        {
            return Results.Json(new { error = "UserId must match the authenticated caller." }, statusCode: StatusCodes.Status403Forbidden);
        }

        if (string.IsNullOrWhiteSpace(request.Action) ||
            string.IsNullOrWhiteSpace(request.ResourceType) ||
            string.IsNullOrWhiteSpace(request.ResourceId))
        {
            return Results.BadRequest(new { error = "Action, ResourceType, and ResourceId are required." });
        }

        var userAgent = httpContext.Request.Headers.UserAgent.ToString();
        var trusted = new AuditEventRequest
        {
            UserId = caller.UserId,
            Action = request.Action,
            ResourceType = request.ResourceType,
            ResourceId = request.ResourceId,
            Details = request.Details,
            IpAddress = CallerIdentity.ClientIpAddress(httpContext),
            UserAgent = string.IsNullOrEmpty(userAgent) ? null : userAgent,
        };

        var response = await auditService.RecordEventAsync(trusted);
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
        IAuditService auditService)
    {
        var pageNumber = page ?? 1;
        var pageSize = Math.Clamp(size ?? 20, 1, 100);

        var result = await auditService.QueryEventsAsync(user_id, action, resource_type, resource, from, to, pageNumber, pageSize);
        return Results.Ok(result);
    }

    private static async Task<IResult> GetEvent(
        string id,
        IAuditService auditService)
    {
        var result = await auditService.GetEventAsync(id);
        return result is not null ? Results.Ok(result) : Results.NotFound(new { error = "Event not found." });
    }

    private static async Task<IResult> GetUserActivityReport(
        string userId,
        string? period,
        IAuditService auditService)
    {
        var reportPeriod = period ?? "30d";
        var report = await auditService.GetUserActivityReportAsync(userId, reportPeriod);
        return Results.Ok(report);
    }

    private static async Task<IResult> GetResourceHistory(
        string resourceId,
        IAuditService auditService)
    {
        var history = await auditService.GetResourceHistoryAsync(resourceId);
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

    internal static async Task<IResult> ArchiveOldEvents(
        HttpContext httpContext,
        IAuditService auditService)
    {
        var caller = CallerIdentity.FromRequest(httpContext.Request);
        if (caller is null)
        {
            return Results.Json(new { error = "Authentication required." }, statusCode: StatusCodes.Status401Unauthorized);
        }

        if (!caller.IsAdmin)
        {
            return Results.Json(new { error = "Archiving audit events requires the ADMIN role." }, statusCode: StatusCodes.Status403Forbidden);
        }

        var result = await auditService.ArchiveOldEventsAsync();
        return Results.Ok(result);
    }
}
