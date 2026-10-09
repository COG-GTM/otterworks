using System.Text;
using System.Text.Json;
using Amazon.S3;
using Amazon.S3.Model;
using Microsoft.Extensions.Options;
using OtterWorks.AuditService.Config;
using OtterWorks.AuditService.Models;

namespace OtterWorks.AuditService.Services;

public class S3AuditArchiver : IAuditArchiver
{
    private readonly IAmazonS3 _s3Client;
    private readonly IAuditRepository _repository;
    private readonly AwsSettings _settings;
    private readonly ILogger<S3AuditArchiver> _logger;

    public S3AuditArchiver(
        IAmazonS3 s3Client,
        IAuditRepository repository,
        IOptions<AwsSettings> settings,
        ILogger<S3AuditArchiver> logger)
    {
        _s3Client = s3Client;
        _repository = repository;
        _settings = settings.Value;
        _logger = logger;
    }

    public async Task<ExportResult> ExportAsync(DateTime from, DateTime to, string format)
    {
        var events = await _repository.GetEventsByDateRangeAsync(from, to);

        string content;
        string contentType;
        string extension;

        if (string.Equals(format, "csv", StringComparison.OrdinalIgnoreCase))
        {
            content = ConvertToCsv(events);
            contentType = "text/csv";
            extension = "csv";
        }
        else
        {
            content = JsonSerializer.Serialize(events, new JsonSerializerOptions { WriteIndented = true });
            contentType = "application/json";
            extension = "json";
        }

        var key = $"{KeyPrefix()}audit-exports/{from:yyyy-MM-dd}_{to:yyyy-MM-dd}_{Guid.NewGuid():N}.{extension}";

        var putRequest = new PutObjectRequest
        {
            BucketName = _settings.S3ArchiveBucket,
            Key = key,
            ContentBody = content,
            ContentType = contentType,
        };

        await _s3Client.PutObjectAsync(putRequest);

        var downloadUrl = $"s3://{_settings.S3ArchiveBucket}/{key}";
        _logger.LogInformation("Exported {Count} audit events to {Url}", events.Count, downloadUrl);

        return new ExportResult
        {
            Format = format,
            EventCount = events.Count,
            DownloadUrl = downloadUrl,
            From = from,
            To = to,
        };
    }

    public async Task<ArchiveResult> ArchiveOldEventsAsync(DateTime olderThan)
    {
        var events = await _repository.GetEventsByDateRangeAsync(DateTime.MinValue, olderThan);

        if (events.Count == 0)
        {
            _logger.LogInformation("No events found older than {OlderThan} to archive", olderThan);
            return new ArchiveResult
            {
                ArchivedCount = 0,
                S3Location = string.Empty,
                ArchivedBefore = olderThan,
            };
        }

        var content = JsonSerializer.Serialize(events, new JsonSerializerOptions { WriteIndented = true });
        var key = $"{KeyPrefix()}audit-archive/{olderThan:yyyy-MM-dd}/{Guid.NewGuid():N}.json";

        var putRequest = new PutObjectRequest
        {
            BucketName = _settings.S3ArchiveBucket,
            Key = key,
            ContentBody = content,
            ContentType = "application/json",
            StorageClass = S3StorageClass.Glacier,
        };

        await _s3Client.PutObjectAsync(putRequest);

        var eventIds = events.Select(e => e.Id);
        var deletedCount = await _repository.DeleteEventsAsync(eventIds);

        var s3Location = $"s3://{_settings.S3ArchiveBucket}/{key}";
        var failedCount = events.Count - deletedCount;

        if (failedCount > 0)
        {
            _logger.LogWarning(
                "Archived {Archived} of {Total} audit events to {Location}; {Failed} events could not be deleted from DynamoDB and may be re-archived on next run",
                deletedCount, events.Count, s3Location, failedCount);
        }
        else
        {
            _logger.LogInformation("Archived {Count} audit events to {Location}", deletedCount, s3Location);
        }

        return new ArchiveResult
        {
            ArchivedCount = deletedCount,
            S3Location = s3Location,
            ArchivedBefore = olderThan,
        };
    }

    private static string ConvertToCsv(List<AuditEvent> events)
    {
        var sb = new StringBuilder();
        sb.AppendLine("Id,Timestamp,UserId,Action,ResourceType,ResourceId,IpAddress,UserAgent");

        foreach (var e in events)
        {
            sb.AppendLine($"\"{Esc(e.Id)}\",\"{e.Timestamp:O}\",\"{Esc(e.UserId)}\",\"{Esc(e.Action)}\",\"{Esc(e.ResourceType)}\",\"{Esc(e.ResourceId)}\",\"{Esc(e.IpAddress)}\",\"{Esc(e.UserAgent)}\"");
        }

        return sb.ToString();
    }

    private string KeyPrefix()
    {
        var trimmed = _settings.S3KeyPrefix.Trim().Trim('/');
        return trimmed.Length == 0 ? string.Empty : trimmed + "/";
    }

    private static string Esc(string? value) =>
        value?.Replace("\"", "\"\"") ?? string.Empty;
}
