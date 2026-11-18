using Amazon.S3;
using Amazon.S3.Model;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Moq;
using OtterWorks.AuditService.Config;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

public class S3AuditArchiverEdgeTests
{
    private readonly Mock<IAmazonS3> _s3 = new();
    private readonly Mock<IAuditRepository> _repository = new();
    private readonly S3AuditArchiver _archiver;

    public S3AuditArchiverEdgeTests()
    {
        _archiver = new S3AuditArchiver(
            _s3.Object,
            _repository.Object,
            Options.Create(new AwsSettings { S3ArchiveBucket = "bucket" }),
            NullLogger<S3AuditArchiver>.Instance);
    }

    [Fact]
    public async Task Archive_WhenSomeDeletesFail_ReportsOnlyDeletedCount()
    {
        var olderThan = new DateTime(2026, 1, 1, 0, 0, 0, DateTimeKind.Utc);
        var events = Enumerable.Range(0, 3)
            .Select(i => new AuditEvent { Id = $"e{i}", Timestamp = olderThan.AddDays(-i - 1) })
            .ToList();
        _repository.Setup(r => r.GetEventsByDateRangeAsync(DateTime.MinValue, olderThan)).ReturnsAsync(events);
        _s3.Setup(s => s.PutObjectAsync(It.IsAny<PutObjectRequest>(), default)).ReturnsAsync(new PutObjectResponse());
        _repository.Setup(r => r.DeleteEventsAsync(It.IsAny<IEnumerable<string>>())).ReturnsAsync(1);

        var result = await _archiver.ArchiveOldEventsAsync(olderThan);

        Assert.Equal(1, result.ArchivedCount);
        Assert.StartsWith("s3://bucket/audit-archive/2026-01-01/", result.S3Location);
        Assert.Equal(olderThan, result.ArchivedBefore);
    }

    [Fact]
    public async Task ExportCsv_EscapesQuotesAndNulls()
    {
        var events = new List<AuditEvent>
        {
            new() { Id = "e1", UserId = "u\"1", Action = "read", ResourceType = "file", ResourceId = "f1", Timestamp = DateTime.UtcNow },
        };
        _repository.Setup(r => r.GetEventsByDateRangeAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>())).ReturnsAsync(events);
        PutObjectRequest? captured = null;
        _s3.Setup(s => s.PutObjectAsync(It.IsAny<PutObjectRequest>(), default))
            .Callback<PutObjectRequest, CancellationToken>((r, _) => captured = r)
            .ReturnsAsync(new PutObjectResponse());

        var result = await _archiver.ExportAsync(DateTime.UtcNow.AddDays(-1), DateTime.UtcNow, "CSV");

        Assert.Equal("CSV", result.Format);
        Assert.Equal("text/csv", captured!.ContentType);
        Assert.EndsWith(".csv", captured.Key);
        var row = captured.ContentBody.Split('\n', StringSplitOptions.RemoveEmptyEntries)[1].TrimEnd('\r');
        Assert.Contains("\"u\"\"1\"", row);
        Assert.EndsWith(",\"\",\"\"", row);
    }
}
