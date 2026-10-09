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

        _archiver = CreateArchiver(new AuditLimits());
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

        SetupEvents(from, to, events);
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

        SetupEvents(from, to, events);
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

        SetupEvents(DateTime.MinValue, olderThan, events);
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

        SetupEvents(DateTime.MinValue, olderThan, new List<AuditEvent>());

        var result = await _archiver.ArchiveOldEventsAsync(olderThan);

        Assert.Equal(0, result.ArchivedCount);
        Assert.Empty(result.S3Location);

        _mockS3.Verify(s => s.PutObjectAsync(It.IsAny<PutObjectRequest>(), default), Times.Never);
        _mockRepository.Verify(r => r.DeleteEventsAsync(It.IsAny<IEnumerable<string>>()), Times.Never);
    }

    [Fact]
    public async Task ExportAsync_ShouldStreamJsonIdenticalToBufferedSerialization()
    {
        var from = DateTime.UtcNow.AddDays(-7);
        var to = DateTime.UtcNow;
        var events = SampleEvents(3);
        SetupEvents(from, to, events);
        var uploaded = CaptureSinglePut();

        var result = await _archiver.ExportAsync(from, to, "json");

        Assert.False(result.Truncated);
        var expected = System.Text.Json.JsonSerializer.Serialize(
            events, new System.Text.Json.JsonSerializerOptions { WriteIndented = true });
        Assert.Equal(expected, uploaded());
    }

    [Fact]
    public async Task ExportAsync_ShouldStreamCsvWithHeaderAndEscaping()
    {
        var from = DateTime.UtcNow.AddDays(-7);
        var to = DateTime.UtcNow;
        var events = SampleEvents(1);
        events[0].UserAgent = "Agent \"quoted\"";
        SetupEvents(from, to, events);
        var uploaded = CaptureSinglePut();

        await _archiver.ExportAsync(from, to, "csv");

        var lines = uploaded().Split(Environment.NewLine, StringSplitOptions.RemoveEmptyEntries);
        Assert.Equal("Id,Timestamp,UserId,Action,ResourceType,ResourceId,IpAddress,UserAgent", lines[0]);
        Assert.Equal(2, lines.Length);
        Assert.EndsWith("\"Agent \"\"quoted\"\"\"", lines[1]);
    }

    [Fact]
    public async Task ExportAsync_ShouldCapEventCountAndMarkTruncated()
    {
        var archiver = CreateArchiver(new AuditLimits { MaxExportEvents = 2 });
        var from = DateTime.UtcNow.AddDays(-7);
        var to = DateTime.UtcNow;
        SetupEvents(from, to, SampleEvents(5));
        _mockS3.Setup(s => s.PutObjectAsync(It.IsAny<PutObjectRequest>(), It.IsAny<CancellationToken>())).ReturnsAsync(new PutObjectResponse());

        var result = await archiver.ExportAsync(from, to, "json");

        Assert.Equal(2, result.EventCount);
        Assert.True(result.Truncated);
    }

    [Fact]
    public async Task ExportAsync_LargeExport_ShouldUseMultipartUploadInBoundedParts()
    {
        var from = DateTime.UtcNow.AddDays(-7);
        var to = DateTime.UtcNow;
        var bigValue = new string('x', 1_000);
        var events = SampleEvents(12_000);
        foreach (var e in events)
            e.Details = new Dictionary<string, string> { ["k"] = bigValue };
        SetupEvents(from, to, events);

        var partSizes = new List<long>();
        _mockS3.Setup(s => s.InitiateMultipartUploadAsync(It.IsAny<InitiateMultipartUploadRequest>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(new InitiateMultipartUploadResponse { UploadId = "upload-1" });
        _mockS3.Setup(s => s.UploadPartAsync(It.IsAny<UploadPartRequest>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync((UploadPartRequest req, CancellationToken _) =>
            {
                partSizes.Add(req.InputStream.Length);
                return new UploadPartResponse { ETag = $"etag-{req.PartNumber}" };
            });
        _mockS3.Setup(s => s.CompleteMultipartUploadAsync(It.IsAny<CompleteMultipartUploadRequest>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(new CompleteMultipartUploadResponse());

        var result = await _archiver.ExportAsync(from, to, "json");

        Assert.Equal(12_000, result.EventCount);
        Assert.True(partSizes.Count >= 2);
        Assert.All(partSizes.SkipLast(1), size => Assert.InRange(size, S3StreamingUpload.PartSize, S3StreamingUpload.PartSize + 64 * 1024));
        _mockS3.Verify(s => s.PutObjectAsync(It.IsAny<PutObjectRequest>(), It.IsAny<CancellationToken>()), Times.Never);
        _mockS3.Verify(s => s.CompleteMultipartUploadAsync(It.Is<CompleteMultipartUploadRequest>(req =>
            req.UploadId == "upload-1" && req.PartETags.Count == partSizes.Count),
            It.IsAny<CancellationToken>()), Times.Once);
    }

    [Fact]
    public async Task ExportAsync_WhenUploadFails_ShouldAbortMultipartUpload()
    {
        var from = DateTime.UtcNow.AddDays(-7);
        var to = DateTime.UtcNow;
        var events = SampleEvents(8_000);
        foreach (var e in events)
            e.Details = new Dictionary<string, string> { ["k"] = new string('x', 1_000) };
        SetupEvents(from, to, events);

        _mockS3.Setup(s => s.InitiateMultipartUploadAsync(It.IsAny<InitiateMultipartUploadRequest>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(new InitiateMultipartUploadResponse { UploadId = "upload-1" });
        _mockS3.Setup(s => s.UploadPartAsync(It.IsAny<UploadPartRequest>(), It.IsAny<CancellationToken>()))
            .ThrowsAsync(new AmazonS3Exception("boom"));
        _mockS3.Setup(s => s.AbortMultipartUploadAsync(It.IsAny<AbortMultipartUploadRequest>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(new AbortMultipartUploadResponse());

        await Assert.ThrowsAsync<AmazonS3Exception>(() => _archiver.ExportAsync(from, to, "json"));

        _mockS3.Verify(s => s.AbortMultipartUploadAsync(It.Is<AbortMultipartUploadRequest>(req => req.UploadId == "upload-1"), It.IsAny<CancellationToken>()), Times.Once);
    }

    [Fact]
    public async Task ArchiveOldEventsAsync_ShouldArchiveAndDeleteInBatches()
    {
        var archiver = CreateArchiver(new AuditLimits { ArchiveBatchSize = 2 });
        var olderThan = DateTime.UtcNow.AddDays(-90);
        SetupEvents(DateTime.MinValue, olderThan, SampleEvents(5));
        var keys = new List<string>();
        _mockS3.Setup(s => s.PutObjectAsync(It.IsAny<PutObjectRequest>(), It.IsAny<CancellationToken>()))
            .Callback((PutObjectRequest req, CancellationToken _) => keys.Add(req.Key))
            .ReturnsAsync(new PutObjectResponse());
        _mockRepository.Setup(r => r.DeleteEventsAsync(It.IsAny<IEnumerable<string>>()))
            .ReturnsAsync((IEnumerable<string> ids) => ids.Count());

        var result = await archiver.ArchiveOldEventsAsync(olderThan);

        Assert.Equal(5, result.ArchivedCount);
        Assert.Equal(3, keys.Count);
        Assert.Equal(3, keys.Distinct().Count());
        _mockRepository.Verify(r => r.DeleteEventsAsync(It.Is<IEnumerable<string>>(ids => ids.Count() == 2)), Times.Exactly(2));
        _mockRepository.Verify(r => r.DeleteEventsAsync(It.Is<IEnumerable<string>>(ids => ids.Count() == 1)), Times.Once);
    }

    private S3AuditArchiver CreateArchiver(AuditLimits limits) =>
        new(_mockS3.Object, _mockRepository.Object, _options, Options.Create(limits), _mockLogger.Object);

    private void SetupEvents(DateTime from, DateTime to, List<AuditEvent> events) =>
        _mockRepository
            .Setup(r => r.StreamEventsByDateRangeAsync(from, to, It.IsAny<CancellationToken>()))
            .Returns(() => events.ToAsyncEnumerable());

    private Func<string> CaptureSinglePut()
    {
        string? body = null;
        _mockS3.Setup(s => s.PutObjectAsync(It.IsAny<PutObjectRequest>(), It.IsAny<CancellationToken>()))
            .Callback((PutObjectRequest req, CancellationToken _) =>
            {
                using var reader = new StreamReader(req.InputStream);
                body = reader.ReadToEnd();
            })
            .ReturnsAsync(new PutObjectResponse());
        return () => body ?? throw new InvalidOperationException("No object uploaded");
    }

    private static List<AuditEvent> SampleEvents(int count) =>
        Enumerable.Range(1, count)
            .Select(i => new AuditEvent
            {
                Id = $"e{i}",
                UserId = "u1",
                Action = "create",
                ResourceType = "doc",
                ResourceId = $"d{i}",
                Timestamp = new DateTime(2024, 1, 1, 0, 0, 0, DateTimeKind.Utc).AddMinutes(i),
            })
            .ToList();
}
