using Amazon.S3;
using Amazon.S3.Model;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Moq;
using OtterWorks.AuditService.Config;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

/// <summary>
/// Covers the archiver's partial-failure branch: events are written to S3 but DynamoDB only
/// deletes some of them, so the result must report the deleted count and warn about the rest.
/// </summary>
public class S3AuditArchiverPartialDeleteTests
{
    private readonly Mock<IAmazonS3> _s3 = new();
    private readonly Mock<IAuditRepository> _repository = new();
    private readonly Mock<ILogger<S3AuditArchiver>> _logger = new();
    private readonly S3AuditArchiver _archiver;

    public S3AuditArchiverPartialDeleteTests()
    {
        _archiver = new S3AuditArchiver(
            _s3.Object,
            _repository.Object,
            Options.Create(new AwsSettings { S3ArchiveBucket = "test-bucket" }),
            _logger.Object);
    }

    [Fact]
    public async Task ArchiveOldEventsAsync_WarnsAndReportsDeletedCount_WhenSomeDeletesFail()
    {
        var cutoff = new DateTime(2026, 1, 1, 0, 0, 0, DateTimeKind.Utc);
        var events = Enumerable.Range(1, 3).Select(i => new AuditEvent
        {
            Id = $"evt-{i}",
            UserId = "user-1",
            Action = "read",
            ResourceType = "file",
            Timestamp = cutoff.AddDays(-i),
        }).ToList();

        _repository
            .Setup(r => r.GetEventsByDateRangeAsync(DateTime.MinValue, cutoff))
            .ReturnsAsync(events);
        _repository
            .Setup(r => r.DeleteEventsAsync(It.IsAny<IEnumerable<string>>()))
            .ReturnsAsync(2);
        PutObjectRequest? putRequest = null;
        _s3
            .Setup(s => s.PutObjectAsync(It.IsAny<PutObjectRequest>(), It.IsAny<CancellationToken>()))
            .Callback<PutObjectRequest, CancellationToken>((r, _) => putRequest = r)
            .ReturnsAsync(new PutObjectResponse());

        var result = await _archiver.ArchiveOldEventsAsync(cutoff);

        Assert.Equal(2, result.ArchivedCount);
        Assert.Equal(cutoff, result.ArchivedBefore);
        Assert.StartsWith("s3://test-bucket/audit-archive/2026-01-01/", result.S3Location);
        Assert.NotNull(putRequest);
        Assert.Equal(S3StorageClass.Glacier, putRequest!.StorageClass);
        Assert.Contains("evt-1", putRequest.ContentBody);
        _logger.Verify(
            l => l.Log(
                LogLevel.Warning,
                It.IsAny<EventId>(),
                It.Is<It.IsAnyType>((state, _) => state.ToString()!.Contains("1 events could not be deleted")),
                It.IsAny<Exception?>(),
                It.IsAny<Func<It.IsAnyType, Exception?, string>>()),
            Times.Once);
    }
}
