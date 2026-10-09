using Microsoft.Extensions.Options;
using OtterWorks.AuditService.Config;
using OtterWorks.AuditService.Models;
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
            .Produces<ComplianceReport>(StatusCodes.Status200OK);

        group.MapGet("/export", ExportAuditLog)
            .WithName("ExportAuditLog")
            .Produces<ExportResult>(StatusCodes.Status200OK);

        group.MapPost("/archive", ArchiveOldEvents)
            .WithName("ArchiveOldEvents")
            .Produces<ArchiveResult>(StatusCodes.Status200OK);
    }

    internal static async Task<IResult> RecordEvent(
        AuditEventRequest request,
        IAuditService auditService,
        IOptions<AuditLimits> limits)
    {
        var error = AuditEventValidator.Validate(request, limits.Value);
        if (error is not null)
            return Results.BadRequest(new { error });

        var response = await auditService.RecordEventAsync(request);
        return Results.Created($"/api/v1/audit/events/{response.Id}", response);
    }

    internal static async Task<IResult> QueryEvents(
        string? user_id,
        string? action,
        string? resource,
        string? resource_type,
        DateTime? from,
        DateTime? to,
        int? page,
        int? size,
        IAuditService auditService,
        IOptions<AuditLimits> limits)
    {
        var pageNumber = Math.Max(page ?? 1, 1);
        var pageSize = Math.Clamp(size ?? 20, 1, 100);

        if ((long)pageNumber * pageSize > limits.Value.MaxQueryWindow)
        {
            return Results.BadRequest(new { error = $"page * size must not exceed {limits.Value.MaxQueryWindow}; narrow the query with filters instead." });
        }

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

    internal static async Task<IResult> ExportAuditLog(
        string? format,
        DateTime? from,
        DateTime? to,
        IAuditService auditService,
        IOptions<AuditLimits> limits)
    {
        var exportFormat = format ?? "json";
        var exportTo = to ?? DateTime.UtcNow;
        if (from is null && exportTo < DateTime.MinValue.AddDays(30))
            return Results.BadRequest(new { error = "'to' is too early; provide 'from' explicitly." });
        var exportFrom = from ?? exportTo.AddDays(-30);
        var maxRangeDays = limits.Value.MaxExportRangeDays;

        if (exportFrom > exportTo)
            return Results.BadRequest(new { error = "'from' must be earlier than 'to'." });

        if (exportTo - exportFrom > TimeSpan.FromDays(maxRangeDays))
            return Results.BadRequest(new { error = $"Export range must not exceed {maxRangeDays} days." });

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
