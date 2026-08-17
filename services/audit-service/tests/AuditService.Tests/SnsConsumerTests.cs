using System.Text.Json;
using Amazon.SQS;
using Amazon.SQS.Model;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Moq;
using OtterWorks.AuditService.Config;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

public class SnsConsumerTests
{
    private const string QueueName = "otterworks-audit-events-queue";
    private const string QueueUrl = "https://sqs.us-east-1.amazonaws.com/000000000000/otterworks-audit-events-queue";

    private readonly Mock<IAmazonSQS> _mockSqs;
    private readonly Mock<IAuditRepository> _mockRepository;
    private readonly Mock<ILogger<SnsConsumer>> _mockLogger;
    private readonly IOptions<AwsSettings> _options;

    public SnsConsumerTests()
    {
        _mockSqs = new Mock<IAmazonSQS>();
        _mockRepository = new Mock<IAuditRepository>();
        _mockLogger = new Mock<ILogger<SnsConsumer>>();
        _options = Options.Create(new AwsSettings { Region = "us-east-1" });
    }

    [Fact]
    public async Task ExecuteAsync_WhenQueueLookupFails_ShouldStopWithoutPolling()
    {
        _mockSqs
            .Setup(s => s.GetQueueUrlAsync(QueueName, It.IsAny<CancellationToken>()))
            .ThrowsAsync(new AmazonSQSException("sqs unavailable"));

        using var cts = new CancellationTokenSource();
        await CreateConsumer().RunAsync(cts.Token);

        _mockSqs.Verify(
            s => s.ReceiveMessageAsync(It.IsAny<ReceiveMessageRequest>(), It.IsAny<CancellationToken>()),
            Times.Never);
        _mockRepository.Verify(r => r.SaveEventAsync(It.IsAny<AuditEvent>()), Times.Never);
    }

    [Fact]
    public async Task ExecuteAsync_WhenQueueDoesNotExist_ShouldCreateItAndPollTheNewQueue()
    {
        _mockSqs
            .Setup(s => s.GetQueueUrlAsync(QueueName, It.IsAny<CancellationToken>()))
            .ThrowsAsync(new QueueDoesNotExistException("missing"));
        _mockSqs
            .Setup(s => s.CreateQueueAsync(It.IsAny<CreateQueueRequest>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(new CreateQueueResponse { QueueUrl = QueueUrl });

        await RunLoopAsync();

        _mockSqs.Verify(
            s => s.CreateQueueAsync(It.Is<CreateQueueRequest>(r => r.QueueName == QueueName), It.IsAny<CancellationToken>()),
            Times.Once);
        _mockSqs.Verify(
            s => s.ReceiveMessageAsync(
                It.Is<ReceiveMessageRequest>(r => r.QueueUrl == QueueUrl && r.MaxNumberOfMessages == 10 && r.WaitTimeSeconds == 20),
                It.IsAny<CancellationToken>()),
            Times.AtLeastOnce);
    }

    [Fact]
    public async Task ExecuteAsync_WithAuditEventMessage_ShouldPersistAndDeleteIt()
    {
        StubExistingQueue();

        var timestamp = new DateTime(2026, 3, 1, 12, 0, 0, DateTimeKind.Utc);
        var body = JsonSerializer.Serialize(new
        {
            userId = "user-1",
            action = "delete",
            resourceType = "file",
            resourceId = "file-9",
            details = new Dictionary<string, string> { ["reason"] = "expired" },
            ipAddress = "10.1.2.3",
            userAgent = "Agent/2.0",
            timestamp,
        });

        await RunLoopAsync(CreateMessage("msg-1", body));

        _mockRepository.Verify(
            r => r.SaveEventAsync(It.Is<AuditEvent>(e =>
                e.Id == "msg-1" &&
                e.UserId == "user-1" &&
                e.Action == "delete" &&
                e.ResourceType == "file" &&
                e.ResourceId == "file-9" &&
                e.IpAddress == "10.1.2.3" &&
                e.UserAgent == "Agent/2.0" &&
                e.Details!["reason"] == "expired" &&
                e.Timestamp == timestamp)),
            Times.Once);
        _mockSqs.Verify(
            s => s.DeleteMessageAsync(QueueUrl, "receipt-msg-1", It.IsAny<CancellationToken>()),
            Times.Once);
    }

    [Fact]
    public async Task ExecuteAsync_WithSparseAuditEventMessage_ShouldApplyDefaults()
    {
        StubExistingQueue();

        var before = DateTime.UtcNow;
        await RunLoopAsync(CreateMessage("msg-2", "{}"));

        _mockRepository.Verify(
            r => r.SaveEventAsync(It.Is<AuditEvent>(e =>
                e.UserId == "system" &&
                e.Action == "unknown" &&
                e.ResourceType == "unknown" &&
                e.ResourceId == string.Empty &&
                e.Timestamp >= before &&
                e.Timestamp <= DateTime.UtcNow)),
            Times.Once);
    }

    [Fact]
    public async Task ExecuteAsync_WithFileSharedEventInSnsEnvelope_ShouldRecordShareEvent()
    {
        StubExistingQueue();

        var timestamp = new DateTime(2026, 4, 2, 8, 30, 0, DateTimeKind.Utc);
        var inner = JsonSerializer.Serialize(new
        {
            eventType = "file_shared",
            fileId = "file-1",
            ownerId = "owner-1",
            sharedWithUserId = "user-2",
            timestamp,
        });
        var envelope = JsonSerializer.Serialize(new { Type = "Notification", Message = inner });

        await RunLoopAsync(CreateMessage("msg-3", envelope));

        _mockRepository.Verify(
            r => r.SaveEventAsync(It.Is<AuditEvent>(e =>
                e.Id == "msg-3" &&
                e.UserId == "owner-1" &&
                e.Action == "share" &&
                e.ResourceType == "file" &&
                e.ResourceId == "file-1" &&
                e.Details!["sharedWithUserId"] == "user-2" &&
                e.Timestamp == timestamp)),
            Times.Once);
        _mockSqs.Verify(
            s => s.DeleteMessageAsync(QueueUrl, "receipt-msg-3", It.IsAny<CancellationToken>()),
            Times.Once);
    }

    [Fact]
    public async Task ExecuteAsync_WithFileSharedEventMissingOwner_ShouldFallBackToSystem()
    {
        StubExistingQueue();

        var body = JsonSerializer.Serialize(new { eventType = "file_shared" });

        await RunLoopAsync(CreateMessage("msg-4", body));

        _mockRepository.Verify(
            r => r.SaveEventAsync(It.Is<AuditEvent>(e =>
                e.UserId == "system" &&
                e.ResourceId == string.Empty &&
                e.Details!["sharedWithUserId"] == string.Empty)),
            Times.Once);
    }

    [Fact]
    public async Task ExecuteAsync_WithNullPayload_ShouldDropMessageWithoutSaving()
    {
        StubExistingQueue();

        var envelope = JsonSerializer.Serialize(new { Type = "Notification", Message = "null" });

        await RunLoopAsync(CreateMessage("msg-5", envelope));

        _mockRepository.Verify(r => r.SaveEventAsync(It.IsAny<AuditEvent>()), Times.Never);
        _mockSqs.Verify(
            s => s.DeleteMessageAsync(QueueUrl, "receipt-msg-5", It.IsAny<CancellationToken>()),
            Times.Once);
    }

    [Fact]
    public async Task ExecuteAsync_WithUnparseableMessage_ShouldKeepMessageOnTheQueue()
    {
        StubExistingQueue();

        await RunLoopAsync(CreateMessage("msg-6", "this is not json"));

        _mockRepository.Verify(r => r.SaveEventAsync(It.IsAny<AuditEvent>()), Times.Never);
        _mockSqs.Verify(
            s => s.DeleteMessageAsync(It.IsAny<string>(), It.IsAny<string>(), It.IsAny<CancellationToken>()),
            Times.Never);
    }

    [Fact]
    public async Task ExecuteAsync_WhenRepositoryThrows_ShouldNotDeleteMessage()
    {
        StubExistingQueue();
        _mockRepository
            .Setup(r => r.SaveEventAsync(It.IsAny<AuditEvent>()))
            .ThrowsAsync(new InvalidOperationException("dynamo down"));

        var body = JsonSerializer.Serialize(new { userId = "user-1", action = "read" });

        await RunLoopAsync(CreateMessage("msg-7", body));

        _mockSqs.Verify(
            s => s.DeleteMessageAsync(It.IsAny<string>(), It.IsAny<string>(), It.IsAny<CancellationToken>()),
            Times.Never);
    }

    [Fact]
    public async Task ExecuteAsync_WhenReceiveIsCancelled_ShouldExitLoopCleanly()
    {
        StubExistingQueue();

        using var cts = new CancellationTokenSource();
        _mockSqs
            .Setup(s => s.ReceiveMessageAsync(It.IsAny<ReceiveMessageRequest>(), It.IsAny<CancellationToken>()))
            .Returns<ReceiveMessageRequest, CancellationToken>((_, _) =>
            {
                cts.Cancel();
                throw new OperationCanceledException(cts.Token);
            });

        await CreateConsumer().RunAsync(cts.Token);

        _mockSqs.Verify(
            s => s.ReceiveMessageAsync(It.IsAny<ReceiveMessageRequest>(), It.IsAny<CancellationToken>()),
            Times.Once);
    }

    [Fact]
    public async Task ExecuteAsync_WhenReceiveFails_ShouldBackOffBeforeRetrying()
    {
        StubExistingQueue();

        using var cts = new CancellationTokenSource();
        _mockSqs
            .Setup(s => s.ReceiveMessageAsync(It.IsAny<ReceiveMessageRequest>(), It.IsAny<CancellationToken>()))
            .Returns<ReceiveMessageRequest, CancellationToken>((_, _) =>
            {
                cts.Cancel();
                throw new AmazonSQSException("throttled");
            });

        // The consumer swallows the SQS failure and awaits its 5s backoff, which observes the
        // cancellation instead of hammering the queue.
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => CreateConsumer().RunAsync(cts.Token));

        _mockRepository.Verify(r => r.SaveEventAsync(It.IsAny<AuditEvent>()), Times.Never);
    }

    private TestableSnsConsumer CreateConsumer() =>
        new(_mockSqs.Object, _mockRepository.Object, _options, _mockLogger.Object);

    private void StubExistingQueue() =>
        _mockSqs
            .Setup(s => s.GetQueueUrlAsync(QueueName, It.IsAny<CancellationToken>()))
            .ReturnsAsync(new GetQueueUrlResponse { QueueUrl = QueueUrl });

    /// <summary>
    /// Delivers <paramref name="messages"/> on the first poll, then cancels so the consumer's
    /// receive loop terminates deterministically.
    /// </summary>
    private async Task RunLoopAsync(params Message[] messages)
    {
        using var cts = new CancellationTokenSource();
        var polls = 0;

        _mockSqs
            .Setup(s => s.ReceiveMessageAsync(It.IsAny<ReceiveMessageRequest>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(() =>
            {
                polls++;
                if (polls > 1)
                {
                    cts.Cancel();
                    return new ReceiveMessageResponse { Messages = new List<Message>() };
                }

                return new ReceiveMessageResponse { Messages = messages.ToList() };
            });

        await CreateConsumer().RunAsync(cts.Token);
    }

    private static Message CreateMessage(string id, string body) =>
        new() { MessageId = id, ReceiptHandle = $"receipt-{id}", Body = body };

    private sealed class TestableSnsConsumer : SnsConsumer
    {
        public TestableSnsConsumer(
            IAmazonSQS sqsClient,
            IAuditRepository repository,
            IOptions<AwsSettings> settings,
            ILogger<SnsConsumer> logger)
            : base(sqsClient, repository, settings, logger)
        {
        }

        public Task RunAsync(CancellationToken stoppingToken) => ExecuteAsync(stoppingToken);
    }
}
