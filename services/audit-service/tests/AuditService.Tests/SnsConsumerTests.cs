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
    private const string QueueUrl = "https://sqs.us-east-1.amazonaws.com/000000000000/" + QueueName;

    private readonly Mock<IAmazonSQS> _mockSqs = new();
    private readonly Mock<IAuditRepository> _mockRepository = new();
    private readonly Mock<ILogger<SnsConsumer>> _mockLogger = new();
    private readonly CancellationTokenSource _cts = new();
    private int _receiveCalls;

    [Fact]
    public async Task ExecuteAsync_ShouldPersistAuditEvent_FromPlainMessage()
    {
        SetupQueueExists();
        var body = JsonSerializer.Serialize(new
        {
            userId = "user-1",
            action = "delete",
            resourceType = "file",
            resourceId = "file-1",
            details = new Dictionary<string, string> { ["reason"] = "cleanup" },
            ipAddress = "10.0.0.9",
            userAgent = "TestAgent/1.0",
            timestamp = "2026-01-15T10:00:00Z",
        });
        SetupReceive(CreateMessage("msg-1", body));

        await RunConsumerAsync();

        _mockRepository.Verify(r => r.SaveEventAsync(It.Is<AuditEvent>(e =>
            e.Id == "msg-1" &&
            e.UserId == "user-1" &&
            e.Action == "delete" &&
            e.ResourceType == "file" &&
            e.ResourceId == "file-1" &&
            e.Details!["reason"] == "cleanup" &&
            e.IpAddress == "10.0.0.9" &&
            e.UserAgent == "TestAgent/1.0")), Times.Once);
        VerifyMessageDeleted("receipt-msg-1");
    }

    [Fact]
    public async Task ExecuteAsync_ShouldFallBackToDefaults_WhenFieldsAreMissing()
    {
        SetupQueueExists();
        SetupReceive(CreateMessage("msg-2", "{}"));

        await RunConsumerAsync();

        _mockRepository.Verify(r => r.SaveEventAsync(It.Is<AuditEvent>(e =>
            e.UserId == "system" &&
            e.Action == "unknown" &&
            e.ResourceType == "unknown" &&
            e.ResourceId == string.Empty &&
            e.Timestamp <= DateTime.UtcNow)), Times.Once);
    }

    [Fact]
    public async Task ExecuteAsync_ShouldPersistShareEvent_FromSnsEnvelope()
    {
        SetupQueueExists();
        var inner = JsonSerializer.Serialize(new
        {
            eventType = "file_shared",
            fileId = "file-7",
            ownerId = "user-7",
            sharedWithUserId = "user-8",
            timestamp = "2026-01-15T10:00:00Z",
        });
        var envelope = JsonSerializer.Serialize(new { Type = "Notification", Message = inner });
        SetupReceive(CreateMessage("msg-3", envelope));

        await RunConsumerAsync();

        _mockRepository.Verify(r => r.SaveEventAsync(It.Is<AuditEvent>(e =>
            e.Id == "msg-3" &&
            e.UserId == "user-7" &&
            e.Action == "share" &&
            e.ResourceType == "file" &&
            e.ResourceId == "file-7" &&
            e.Details!["sharedWithUserId"] == "user-8")), Times.Once);
        VerifyMessageDeleted("receipt-msg-3");
    }

    [Fact]
    public async Task ExecuteAsync_ShouldDropMessage_WhenPayloadDeserialisesToNull()
    {
        SetupQueueExists();
        SetupReceive(CreateMessage("msg-4", JsonSerializer.Serialize(new { Message = "null" })));

        await RunConsumerAsync();

        _mockRepository.Verify(r => r.SaveEventAsync(It.IsAny<AuditEvent>()), Times.Never);
        VerifyMessageDeleted("receipt-msg-4");
    }

    [Fact]
    public async Task ExecuteAsync_ShouldKeepMessage_WhenBodyIsNotJson()
    {
        SetupQueueExists();
        SetupReceive(CreateMessage("msg-5", "not-json"));

        await RunConsumerAsync();

        _mockRepository.Verify(r => r.SaveEventAsync(It.IsAny<AuditEvent>()), Times.Never);
        _mockSqs.Verify(
            s => s.DeleteMessageAsync(It.IsAny<string>(), It.IsAny<string>(), It.IsAny<CancellationToken>()),
            Times.Never);
    }

    [Fact]
    public async Task ExecuteAsync_ShouldKeepMessage_WhenRepositoryThrows()
    {
        SetupQueueExists();
        SetupReceive(CreateMessage("msg-6", "{\"userId\":\"user-1\"}"));
        _mockRepository
            .Setup(r => r.SaveEventAsync(It.IsAny<AuditEvent>()))
            .ThrowsAsync(new InvalidOperationException("dynamo down"));

        await RunConsumerAsync();

        _mockSqs.Verify(
            s => s.DeleteMessageAsync(It.IsAny<string>(), It.IsAny<string>(), It.IsAny<CancellationToken>()),
            Times.Never);
    }

    [Fact]
    public async Task ExecuteAsync_ShouldCreateQueue_WhenItDoesNotExist()
    {
        _mockSqs
            .Setup(s => s.GetQueueUrlAsync(QueueName, It.IsAny<CancellationToken>()))
            .ThrowsAsync(new QueueDoesNotExistException("missing"));
        _mockSqs
            .Setup(s => s.CreateQueueAsync(It.IsAny<CreateQueueRequest>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(new CreateQueueResponse { QueueUrl = QueueUrl });
        SetupReceive();

        await RunConsumerAsync();

        _mockSqs.Verify(
            s => s.CreateQueueAsync(It.Is<CreateQueueRequest>(r => r.QueueName == QueueName), It.IsAny<CancellationToken>()),
            Times.Once);
    }

    [Fact]
    public async Task ExecuteAsync_ShouldStop_WhenQueueInitialisationFails()
    {
        _mockSqs
            .Setup(s => s.GetQueueUrlAsync(QueueName, It.IsAny<CancellationToken>()))
            .ThrowsAsync(new AmazonSQSException("no credentials"));

        await RunConsumerAsync();

        _mockSqs.Verify(
            s => s.ReceiveMessageAsync(It.IsAny<ReceiveMessageRequest>(), It.IsAny<CancellationToken>()),
            Times.Never);
    }

    [Fact]
    public async Task ExecuteAsync_ShouldExitLoop_WhenReceiveIsCancelled()
    {
        SetupQueueExists();
        _mockSqs
            .Setup(s => s.ReceiveMessageAsync(It.IsAny<ReceiveMessageRequest>(), It.IsAny<CancellationToken>()))
            .Returns(() =>
            {
                _cts.Cancel();
                throw new OperationCanceledException();
            });

        await RunConsumerAsync();

        _mockSqs.Verify(
            s => s.ReceiveMessageAsync(It.IsAny<ReceiveMessageRequest>(), It.IsAny<CancellationToken>()),
            Times.Once);
    }

    [Fact]
    public async Task ExecuteAsync_ShouldBackOff_WhenReceiveFails()
    {
        SetupQueueExists();
        _mockSqs
            .Setup(s => s.ReceiveMessageAsync(It.IsAny<ReceiveMessageRequest>(), It.IsAny<CancellationToken>()))
            .Returns(() =>
            {
                // Cancelling here makes the consumer's back-off delay complete immediately.
                _cts.Cancel();
                throw new AmazonSQSException("throttled");
            });

        var consumer = CreateConsumer();

        await Assert.ThrowsAnyAsync<OperationCanceledException>(async () =>
        {
            await consumer.StartAsync(_cts.Token);
            await consumer.ExecuteTask!;
        });

        _mockRepository.Verify(r => r.SaveEventAsync(It.IsAny<AuditEvent>()), Times.Never);
    }

    private SnsConsumer CreateConsumer() => new(
        _mockSqs.Object,
        _mockRepository.Object,
        Options.Create(new AwsSettings { Region = "us-east-1" }),
        _mockLogger.Object);

    private async Task RunConsumerAsync()
    {
        var consumer = CreateConsumer();
        await consumer.StartAsync(_cts.Token);
        await consumer.ExecuteTask!;
        await consumer.StopAsync(CancellationToken.None);
    }

    private void SetupQueueExists() =>
        _mockSqs
            .Setup(s => s.GetQueueUrlAsync(QueueName, It.IsAny<CancellationToken>()))
            .ReturnsAsync(new GetQueueUrlResponse { QueueUrl = QueueUrl });

    /// <summary>
    /// Serves <paramref name="messages"/> on the first poll, then cancels so the loop exits.
    /// </summary>
    private void SetupReceive(params Message[] messages) =>
        _mockSqs
            .Setup(s => s.ReceiveMessageAsync(It.IsAny<ReceiveMessageRequest>(), It.IsAny<CancellationToken>()))
            .Returns(() =>
            {
                if (Interlocked.Increment(ref _receiveCalls) > 1)
                {
                    _cts.Cancel();
                    return Task.FromResult(new ReceiveMessageResponse { Messages = new List<Message>() });
                }

                return Task.FromResult(new ReceiveMessageResponse { Messages = messages.ToList() });
            });

    private void VerifyMessageDeleted(string receiptHandle) =>
        _mockSqs.Verify(
            s => s.DeleteMessageAsync(QueueUrl, receiptHandle, It.IsAny<CancellationToken>()),
            Times.Once);

    private static Message CreateMessage(string id, string body) => new()
    {
        MessageId = id,
        ReceiptHandle = $"receipt-{id}",
        Body = body,
    };
}
