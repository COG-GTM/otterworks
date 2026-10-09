using Amazon.S3;
using Microsoft.Extensions.Options;
using OtterWorks.AuditService.Config;
using OtterWorks.AuditService.Models;

namespace OtterWorks.AuditService.Services;

public class S3AuditArchiver : IAuditArchiver
{
    private readonly IAmazonS3 _s3Client;
    private readonly IAuditRepository _repository;
    private readonly AwsSettings _settings;
    private readonly AuditLimits _limits;
    private readonly ILogger<S3AuditArchiver> _logger;

    public S3AuditArchiver(
        IAmazonS3 s3Client,
        IAuditRepository repository,
        IOptions<AwsSettings> settings,
        IOptions<AuditLimits> limits,
        ILogger<S3AuditArchiver> logger)
    {
        _s3Client = s3Client;
        _repository = repository;
        _settings = settings.Value;
        _limits = limits.Value;
        _logger = logger;
    }

    public async Task<ExportResult> ExportAsync(DateTime from, DateTime to, string format)
    {
        var csv = string.Equals(format, "csv", StringComparison.OrdinalIgnoreCase);
        var contentType = csv ? "text/csv" : "application/json";
        var extension = csv ? "csv" : "json";
        var key = $"audit-exports/{from:yyyy-MM-dd}_{to:yyyy-MM-dd}_{Guid.NewGuid():N}.{extension}";

        var count = 0;
        var truncated = false;

        await using (var upload = new S3StreamingUpload(_s3Client, _settings.S3ArchiveBucket, key, contentType))
        {
            using var writer = AuditEventWriter.Create(upload.Buffer, csv);
            await foreach (var auditEvent in _repository.StreamEventsByDateRangeAsync(from, to))
            {
                if (count >= _limits.MaxExportEvents)
                {
                    truncated = true;
                    break;
                }

                writer.Write(auditEvent);
                count++;
                writer.Flush();
                await upload.FlushIfFullAsync();
            }

            writer.Finish();
            await upload.CompleteAsync();
        }

        var downloadUrl = $"s3://{_settings.S3ArchiveBucket}/{key}";
        if (truncated)
        {
            _logger.LogWarning("Export to {Url} truncated at {Count} events (limit {Limit})", downloadUrl, count, _limits.MaxExportEvents);
        }
        else
        {
            _logger.LogInformation("Exported {Count} audit events to {Url}", count, downloadUrl);
        }

        return new ExportResult
        {
            Format = format,
            EventCount = count,
            DownloadUrl = downloadUrl,
            From = from,
            To = to,
            Truncated = truncated,
        };
    }

    public async Task<ArchiveResult> ArchiveOldEventsAsync(DateTime olderThan)
    {
        var runId = Guid.NewGuid().ToString("N");
        var batchIds = new List<string>();
        var batchKeys = new List<string>();
        var total = 0;
        var deletedCount = 0;
        S3StreamingUpload? upload = null;
        AuditEventWriter? writer = null;

        try
        {
            await foreach (var auditEvent in _repository.StreamEventsByDateRangeAsync(DateTime.MinValue, olderThan))
            {
                if (upload is null)
                {
                    var suffix = batchKeys.Count == 0 ? string.Empty : $"-{batchKeys.Count + 1:D4}";
                    var key = $"audit-archive/{olderThan:yyyy-MM-dd}/{runId}{suffix}.json";
                    batchKeys.Add(key);
                    upload = new S3StreamingUpload(_s3Client, _settings.S3ArchiveBucket, key, "application/json", S3StorageClass.Glacier);
                    writer = AuditEventWriter.Create(upload.Buffer, csv: false);
                }

                writer!.Write(auditEvent);
                writer.Flush();
                batchIds.Add(auditEvent.Id);
                total++;
                await upload.FlushIfFullAsync();

                if (batchIds.Count >= _limits.ArchiveBatchSize)
                {
                    deletedCount += await CompleteArchiveBatchAsync(upload, writer, batchIds);
                    upload = null;
                    writer = null;
                }
            }

            if (upload is not null)
            {
                deletedCount += await CompleteArchiveBatchAsync(upload, writer!, batchIds);
                upload = null;
                writer = null;
            }
        }
        finally
        {
            writer?.Dispose();
            if (upload is not null)
                await upload.DisposeAsync();
        }

        if (total == 0)
        {
            _logger.LogInformation("No events found older than {OlderThan} to archive", olderThan);
            return new ArchiveResult
            {
                ArchivedCount = 0,
                S3Location = string.Empty,
                ArchivedBefore = olderThan,
            };
        }

        var s3Location = batchKeys.Count == 1
            ? $"s3://{_settings.S3ArchiveBucket}/{batchKeys[0]}"
            : $"s3://{_settings.S3ArchiveBucket}/audit-archive/{olderThan:yyyy-MM-dd}/{runId}";
        var failedCount = total - deletedCount;

        if (failedCount > 0)
        {
            _logger.LogWarning(
                "Archived {Archived} of {Total} audit events to {Location}; {Failed} events could not be deleted from DynamoDB and may be re-archived on next run",
                deletedCount, total, s3Location, failedCount);
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

    private async Task<int> CompleteArchiveBatchAsync(S3StreamingUpload upload, AuditEventWriter writer, List<string> batchIds)
    {
        try
        {
            writer.Finish();
            await upload.CompleteAsync();
        }
        finally
        {
            writer.Dispose();
            await upload.DisposeAsync();
        }

        var deleted = await _repository.DeleteEventsAsync(batchIds.ToList());
        batchIds.Clear();
        return deleted;
    }
}
