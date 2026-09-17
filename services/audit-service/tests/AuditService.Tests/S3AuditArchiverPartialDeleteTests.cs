using Amazon.S3;
using Amazon.S3.Model;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Moq;
using OtterWorks.AuditService.Config;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

public class S3AuditArchiverPartialDeleteTests
{
    private readonly Mock<IAmazonS3> _mockS3 = new();
    private readonly Mock<IAuditRepository> _mockRepository = new();
    private readonly Mock<ILogger<S3AuditArchiver>> _mockLogger = new();
    private readonly S3AuditArchiver _archiver;

    public S3AuditArchiverPartialDeleteTests()
    {
        _archiver = new S3AuditArchiver(
            _mockS3.Object,
            _mockRepository.Object,
            Options.Create(new AwsSettings { S3ArchiveBucket = "test-bucket" }),
            _mockLogger.Object);
    }

    [Fact]
    public async Task ArchiveOldEventsAsync_ShouldReportOnlyDeletedEvents_WhenSomeDeletesFail()
    {
        var olderThan = DateTime.UtcNow.AddDays(-90);
        var events = Enumerable.Range(0, 3)
            .Select(i => new AuditEvent { Id = $"e{i}", UserId = "user-1", Timestamp = olderThan.AddDays(-1) })
            .ToList();

        _mockRepository
            .Setup(r => r.GetEventsByDateRangeAsync(DateTime.MinValue, olderThan))
            .ReturnsAsync(events);
        _mockRepository
            .Setup(r => r.DeleteEventsAsync(It.IsAny<IEnumerable<string>>()))
            .ReturnsAsync(2);
        _mockS3
            .Setup(s => s.PutObjectAsync(It.IsAny<PutObjectRequest>(), default))
            .ReturnsAsync(new PutObjectResponse());

        var result = await _archiver.ArchiveOldEventsAsync(olderThan);

        Assert.Equal(2, result.ArchivedCount);
        Assert.StartsWith("s3://test-bucket/audit-archive/", result.S3Location);
        Assert.Equal(olderThan, result.ArchivedBefore);

        _mockLogger.Verify(
            l => l.Log(
                LogLevel.Warning,
                It.IsAny<EventId>(),
                It.IsAny<It.IsAnyType>(),
                It.IsAny<Exception?>(),
                It.IsAny<Func<It.IsAnyType, Exception?, string>>()),
            Times.Once);
    }
}
