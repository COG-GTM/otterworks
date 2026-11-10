using Microsoft.AspNetCore.Mvc;
using OtterWorks.AuditService.Auth;
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
            .RequireAuthorization(AuditAuth.IngestPolicy)
            .Produces<AuditEventResponse>(StatusCodes.Status201Created)
            .Produces(StatusCodes.Status400BadRequest)
            .Produces(StatusCodes.Status401Unauthorized);

        var admin = group.MapGroup(string.Empty).RequireAuthorization(AuditAuth.AdminPolicy);

        admin.MapGet("/events", QueryEvents)
            .WithName("QueryAuditEvents")
            .Produces<AuditEventPage>(StatusCodes.Status200OK);

        admin.MapGet("/events/{id}", GetEvent)
            .WithName("GetAuditEvent")
            .Produces<AuditEventResponse>(StatusCodes.Status200OK)
            .Produces(StatusCodes.Status404NotFound);

        admin.MapGet("/reports/user/{userId}", GetUserActivityReport)
            .WithName("GetUserActivityReport")
            .WithMetadata(new SelfAuditMetadata(SelfAuditActions.UserReportRead, "user", "userId"))
            .Produces<UserActivityReport>(StatusCodes.Status200OK);

        admin.MapGet("/resources/{resourceId}/history", GetResourceHistory)
            .WithName("GetResourceHistory")
            .Produces<ResourceHistory>(StatusCodes.Status200OK);

        admin.MapGet("/reports/compliance", GetComplianceReport)
            .WithName("GetComplianceReport")
            .Produces<ComplianceReport>(StatusCodes.Status200OK);

        admin.MapGet("/export", ExportAuditLog)
            .WithName("ExportAuditLog")
            .WithMetadata(new SelfAuditMetadata(SelfAuditActions.Export, "export_archive"))
            .Produces<ExportResult>(StatusCodes.Status200OK);

        admin.MapPost("/archive", ArchiveOldEvents)
            .WithName("ArchiveOldEvents")
            .WithMetadata(new SelfAuditMetadata(SelfAuditActions.Archive, "audit_log"))
            .Produces<ArchiveResult>(StatusCodes.Status200OK);
    }

    private static async Task<IResult> RecordEvent(
        AuditEventRequest request,
        IAuditService auditService)
    {
        var errors = AuditContract.Validate(request);
        if (errors.Count > 0)
        {
            return Results.BadRequest(new { error = "Invalid audit event.", errors });
        }

        var response = await auditService.RecordEventAsync(request);
        return Results.Created($"/api/v1/audit/events/{response.Id}", response);
    }

    private static async Task<IResult> QueryEvents(
        [AsParameters] AuditEventQueryParameters query,
        IAuditService auditService)
    {
        var result = await auditService.QueryEventsAsync(query.ToQuery());
        return Results.Ok(new
        {
            events = result.Events.Select(AuditEventResponse.FromEntity).ToList(),
            total = result.Total,
            page = result.Page,
            pageSize = result.PageSize,
        });
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
        HttpContext context,
        IAuditService auditService,
        SelfAuditor selfAuditor)
    {
        var reportPeriod = period ?? "30d";
        var details = new Dictionary<string, string> { ["report"] = "user_activity", ["period"] = reportPeriod };
        try
        {
            var report = await auditService.GetUserActivityReportAsync(userId, reportPeriod);
            details["eventCount"] = report.TotalEvents.ToString();
            await selfAuditor.RecordAsync(context, SelfAuditActions.UserReportRead, "user", userId, "success", details);
            return Results.Ok(report);
        }
        catch (Exception ex)
        {
            details["error"] = ex.GetType().Name;
            await selfAuditor.RecordAsync(context, SelfAuditActions.UserReportRead, "user", userId, "failure", details);
            throw;
        }
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
        HttpContext context,
        IAuditService auditService,
        SelfAuditor selfAuditor)
    {
        var exportFormat = format ?? "json";
        var exportFrom = from ?? DateTime.UtcNow.AddDays(-30);
        var exportTo = to ?? DateTime.UtcNow;
        var details = new Dictionary<string, string>
        {
            ["format"] = exportFormat,
            ["from"] = exportFrom.ToString("O"),
            ["to"] = exportTo.ToString("O"),
        };

        if (!string.Equals(exportFormat, "csv", StringComparison.OrdinalIgnoreCase) &&
            !string.Equals(exportFormat, "json", StringComparison.OrdinalIgnoreCase))
        {
            details["reason"] = "invalid_format";
            await selfAuditor.RecordAsync(context, SelfAuditActions.Export, "export_archive", string.Empty, "failure", details);
            return Results.BadRequest(new { error = "Format must be 'csv' or 'json'." });
        }

        try
        {
            var result = await auditService.ExportAsync(exportFrom, exportTo, exportFormat);
            details["eventCount"] = result.EventCount.ToString();
            await selfAuditor.RecordAsync(context, SelfAuditActions.Export, "export_archive", StripQuery(result.DownloadUrl), "success", details);
            return Results.Ok(result);
        }
        catch (Exception ex)
        {
            details["error"] = ex.GetType().Name;
            await selfAuditor.RecordAsync(context, SelfAuditActions.Export, "export_archive", string.Empty, "failure", details);
            throw;
        }
    }

    private static async Task<IResult> ArchiveOldEvents(
        HttpContext context,
        IAuditService auditService,
        SelfAuditor selfAuditor)
    {
        try
        {
            var result = await auditService.ArchiveOldEventsAsync();
            await selfAuditor.RecordAsync(context, SelfAuditActions.Archive, "audit_log", StripQuery(result.S3Location), "success",
                new Dictionary<string, string>
                {
                    ["archivedCount"] = result.ArchivedCount.ToString(),
                    ["archivedBefore"] = result.ArchivedBefore.ToString("O"),
                    ["storageClass"] = result.StorageClass,
                });
            return Results.Ok(result);
        }
        catch (Exception ex)
        {
            await selfAuditor.RecordAsync(context, SelfAuditActions.Archive, "audit_log", string.Empty, "failure",
                new Dictionary<string, string> { ["error"] = ex.GetType().Name });
            throw;
        }
    }

    // Presigned URLs carry a signature in the query string; it must never land in an audit record.
    private static string StripQuery(string url)
    {
        var index = url.IndexOf('?');
        return index < 0 ? url : url[..index];
    }
}

public static class SelfAuditActions
{
    public const string Export = "export";
    public const string Archive = "delete";
    public const string UserReportRead = "audit.report.read";
}

public sealed class AuditEventQueryParameters
{
    [FromQuery(Name = "user_id")] public string? UserIdSnake { get; set; }
    [FromQuery(Name = "userId")] public string? UserId { get; set; }
    [FromQuery(Name = "action")] public string? Action { get; set; }
    [FromQuery(Name = "outcome")] public string? Outcome { get; set; }
    [FromQuery(Name = "resource")] public string? Resource { get; set; }
    [FromQuery(Name = "resourceId")] public string? ResourceId { get; set; }
    [FromQuery(Name = "resource_type")] public string? ResourceTypeSnake { get; set; }
    [FromQuery(Name = "resourceType")] public string? ResourceType { get; set; }
    [FromQuery(Name = "service_name")] public string? ServiceNameSnake { get; set; }
    [FromQuery(Name = "serviceName")] public string? ServiceName { get; set; }
    [FromQuery(Name = "tenant_id")] public string? TenantIdSnake { get; set; }
    [FromQuery(Name = "tenantId")] public string? TenantId { get; set; }
    [FromQuery(Name = "from")] public DateTime? From { get; set; }
    [FromQuery(Name = "to")] public DateTime? To { get; set; }
    [FromQuery(Name = "page")] public int? Page { get; set; }
    [FromQuery(Name = "size")] public int? Size { get; set; }

    public AuditEventQuery ToQuery() => new()
    {
        UserId = UserIdSnake ?? UserId,
        Action = Action,
        Outcome = Outcome,
        ResourceId = Resource ?? ResourceId,
        ResourceType = ResourceTypeSnake ?? ResourceType,
        ServiceName = ServiceNameSnake ?? ServiceName,
        TenantId = TenantIdSnake ?? TenantId,
        From = From,
        To = To,
        Page = Math.Max(Page ?? 1, 1),
        PageSize = Math.Clamp(Size ?? 20, 1, 100),
    };
}
