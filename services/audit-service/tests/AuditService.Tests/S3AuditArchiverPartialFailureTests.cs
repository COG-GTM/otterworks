using Amazon.S3;
using Amazon.S3.Model;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Moq;
using OtterWorks.AuditService.Config;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

public class S3AuditArchiverPartialFailureTests
{
    private readonly Mock<IAmazonS3> _mockS3;
    private readonly Mock<IAuditRepository> _mockRepository;
    private readonly S3AuditArchiver _archiver;

    public S3AuditArchiverPartialFailureTests()
    {
        _mockS3 = new Mock<IAmazonS3>();
        _mockRepository = new Mock<IAuditRepository>();
        _archiver = new S3AuditArchiver(
            _mockS3.Object,
            _mockRepository.Object,
            Options.Create(new AwsSettings { S3ArchiveBucket = "test-archive-bucket" }),
            new Mock<ILogger<S3AuditArchiver>>().Object);
    }

    [Fact]
    public async Task ArchiveOldEventsAsync_WhenSomeDeletesFail_ShouldReportOnlyDeletedEvents()
    {
        var olderThan = DateTime.UtcNow.AddDays(-90);
        var events = new List<AuditEvent>
        {
            new() { Id = "e1", UserId = "u1", Timestamp = DateTime.UtcNow.AddDays(-100) },
            new() { Id = "e2", UserId = "u1", Timestamp = DateTime.UtcNow.AddDays(-120) },
            new() { Id = "e3", UserId = "u2", Timestamp = DateTime.UtcNow.AddDays(-140) },
        };

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
        Assert.StartsWith("s3://test-archive-bucket/audit-archive/", result.S3Location, StringComparison.Ordinal);
        Assert.Equal(olderThan, result.ArchivedBefore);

        _mockS3.Verify(s => s.PutObjectAsync(
            It.Is<PutObjectRequest>(r => r.StorageClass == S3StorageClass.Glacier), default), Times.Once);
        _mockRepository.Verify(
            r => r.DeleteEventsAsync(It.Is<IEnumerable<string>>(ids => ids.SequenceEqual(new[] { "e1", "e2", "e3" }))),
            Times.Once);
    }
}
