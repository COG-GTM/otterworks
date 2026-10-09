using Amazon.S3;
using Amazon.S3.Model;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Moq;
using OtterWorks.AuditService.Config;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

public class S3AuditArchiverTests
{
    private readonly Mock<IAmazonS3> _mockS3;
    private readonly Mock<IAuditRepository> _mockRepository;
    private readonly Mock<ILogger<S3AuditArchiver>> _mockLogger;
    private readonly IOptions<AwsSettings> _options;
    private readonly S3AuditArchiver _archiver;

    public S3AuditArchiverTests()
    {
        _mockS3 = new Mock<IAmazonS3>();
        _mockRepository = new Mock<IAuditRepository>();
        _mockLogger = new Mock<ILogger<S3AuditArchiver>>();
        _options = Options.Create(new AwsSettings
        {
            S3ArchiveBucket = "test-archive-bucket",
            Region = "us-east-1",
        });

        _archiver = new S3AuditArchiver(_mockS3.Object, _mockRepository.Object, _options, _mockLogger.Object);
    }

    [Fact]
    public async Task ExportAsync_WithJsonFormat_ShouldUploadJsonToS3()
    {
        var from = DateTime.UtcNow.AddDays(-7);
        var to = DateTime.UtcNow;
        var events = new List<AuditEvent>
        {
            new() { Id = "e1", UserId = "u1", Action = "create", ResourceType = "doc", ResourceId = "d1", Timestamp = DateTime.UtcNow },
        };

        _mockRepository.Setup(r => r.GetEventsByDateRangeAsync(from, to)).ReturnsAsync(events);
        _mockS3.Setup(s => s.PutObjectAsync(It.IsAny<PutObjectRequest>(), default)).ReturnsAsync(new PutObjectResponse());

        var result = await _archiver.ExportAsync(from, to, "json");

        Assert.Equal("json", result.Format);
        Assert.Equal(1, result.EventCount);
        Assert.Contains("test-archive-bucket", result.DownloadUrl);
        Assert.Contains(".json", result.DownloadUrl);

        _mockS3.Verify(s => s.PutObjectAsync(It.Is<PutObjectRequest>(req =>
            req.BucketName == "test-archive-bucket" &&
            req.ContentType == "application/json"),
            default), Times.Once);
    }

    [Fact]
    public async Task ExportAsync_WithCsvFormat_ShouldUploadCsvToS3()
    {
        var from = DateTime.UtcNow.AddDays(-7);
        var to = DateTime.UtcNow;
        var events = new List<AuditEvent>
        {
            new() { Id = "e1", UserId = "u1", Action = "create", ResourceType = "doc", ResourceId = "d1", Timestamp = DateTime.UtcNow },
        };

        _mockRepository.Setup(r => r.GetEventsByDateRangeAsync(from, to)).ReturnsAsync(events);
        _mockS3.Setup(s => s.PutObjectAsync(It.IsAny<PutObjectRequest>(), default)).ReturnsAsync(new PutObjectResponse());

        var result = await _archiver.ExportAsync(from, to, "csv");

        Assert.Equal("csv", result.Format);
        Assert.Equal(1, result.EventCount);
        Assert.Contains(".csv", result.DownloadUrl);

        _mockS3.Verify(s => s.PutObjectAsync(It.Is<PutObjectRequest>(req =>
            req.ContentType == "text/csv"),
            default), Times.Once);
    }

    [Fact]
    public async Task ArchiveOldEventsAsync_WithEvents_ShouldUploadToGlacierAndDelete()
    {
        var olderThan = DateTime.UtcNow.AddDays(-90);
        var events = new List<AuditEvent>
        {
            new() { Id = "old-1", UserId = "u1", Action = "create", ResourceType = "doc", ResourceId = "d1", Timestamp = olderThan.AddDays(-10) },
            new() { Id = "old-2", UserId = "u2", Action = "update", ResourceType = "doc", ResourceId = "d2", Timestamp = olderThan.AddDays(-5) },
        };

        _mockRepository.Setup(r => r.GetArchivableEventsAsync(olderThan)).ReturnsAsync(events);
        _mockS3.Setup(s => s.PutObjectAsync(It.IsAny<PutObjectRequest>(), default)).ReturnsAsync(new PutObjectResponse());
        _mockRepository.Setup(r => r.DeleteEventsAsync(It.IsAny<IEnumerable<string>>())).ReturnsAsync(2);

        var result = await _archiver.ArchiveOldEventsAsync(olderThan);

        Assert.Equal(2, result.ArchivedCount);
        Assert.Contains("test-archive-bucket", result.S3Location);
        Assert.Equal("GLACIER", result.StorageClass);

        _mockS3.Verify(s => s.PutObjectAsync(It.Is<PutObjectRequest>(req =>
            req.StorageClass == S3StorageClass.Glacier &&
            req.BucketName == "test-archive-bucket"),
            default), Times.Once);

        _mockRepository.Verify(r => r.DeleteEventsAsync(
            It.Is<IEnumerable<string>>(ids => ids.Count() == 2)), Times.Once);
    }

    [Fact]
    public async Task ArchiveOldEventsAsync_WithNoEvents_ShouldReturnZeroCount()
    {
        var olderThan = DateTime.UtcNow.AddDays(-90);

        _mockRepository
            .Setup(r => r.GetArchivableEventsAsync(olderThan))
            .ReturnsAsync(new List<AuditEvent>());

        var result = await _archiver.ArchiveOldEventsAsync(olderThan);

        Assert.Equal(0, result.ArchivedCount);
        Assert.Empty(result.S3Location);

        _mockS3.Verify(s => s.PutObjectAsync(It.IsAny<PutObjectRequest>(), default), Times.Never);
        _mockRepository.Verify(r => r.DeleteEventsAsync(It.IsAny<IEnumerable<string>>()), Times.Never);
    }

    [Fact]
    public async Task ArchiveOldEventsAsync_ShouldOnlyArchiveTenantScopedEventsUnderTenantPrefix()
    {
        var archiver = new S3AuditArchiver(_mockS3.Object, _mockRepository.Object, Options.Create(new AwsSettings
        {
            S3ArchiveBucket = "test-archive-bucket",
            Region = "us-east-1",
            TenantId = "tenant-a",
        }), _mockLogger.Object);
        var olderThan = DateTime.UtcNow.AddDays(-90);
        var events = new List<AuditEvent>
        {
            new() { Id = "old-1", UserId = "u1", Action = "create", ResourceType = "doc", ResourceId = "d1", Timestamp = olderThan.AddDays(-1) },
        };

        _mockRepository.Setup(r => r.GetArchivableEventsAsync(olderThan)).ReturnsAsync(events);
        _mockS3.Setup(s => s.PutObjectAsync(It.IsAny<PutObjectRequest>(), default)).ReturnsAsync(new PutObjectResponse());
        _mockRepository.Setup(r => r.DeleteEventsAsync(It.IsAny<IEnumerable<string>>())).ReturnsAsync(1);

        await archiver.ArchiveOldEventsAsync(olderThan);

        _mockS3.Verify(s => s.PutObjectAsync(It.Is<PutObjectRequest>(req =>
            req.Key.StartsWith("audit-archive/tenant-a/")),
            default), Times.Once);
        _mockRepository.Verify(r => r.GetEventsByDateRangeAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>()), Times.Never);
        _mockRepository.Verify(r => r.DeleteEventsAsync(
            It.Is<IEnumerable<string>>(ids => ids.SequenceEqual(new[] { "old-1" }))), Times.Once);
    }
}
