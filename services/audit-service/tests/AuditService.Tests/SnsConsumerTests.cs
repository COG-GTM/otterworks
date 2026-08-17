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
    private const string QueueUrl = "https://sqs.test/queue/otterworks-audit-events-queue";

    private readonly Mock<IAmazonSQS> _mockSqs = new();
    private readonly Mock<IAuditRepository> _mockRepository = new();
    private readonly Mock<ILogger<SnsConsumer>> _mockLogger = new();
    private readonly IOptions<AwsSettings> _options = Options.Create(new AwsSettings
    {
        DynamoDbTable = "test-audit-events",
        Region = "us-east-1",
    });

    [Fact]
    public async Task ExecuteAsync_ShouldPersistAndDeleteAuditEvent_WhenMessageIsPlainJson()
    {
        SetupQueueUrl();
        var body = JsonSerializer.Serialize(new
        {
            userId = "user-1",
            action = "delete",
            resourceType = "file",
            resourceId = "file-9",
            ipAddress = "10.0.0.5",
            userAgent = "TestAgent",
            timestamp = new DateTime(2026, 1, 2, 3, 4, 5, DateTimeKind.Utc),
            details = new Dictionary<string, string> { ["reason"] = "cleanup" },
        });

        AuditEvent? saved = null;
        _mockRepository
            .Setup(r => r.SaveEventAsync(It.IsAny<AuditEvent>()))
            .Callback<AuditEvent>(e => saved = e)
            .Returns(Task.CompletedTask);

        await RunConsumerAsync(new Message { MessageId = "msg-1", ReceiptHandle = "rh-1", Body = body });

        Assert.NotNull(saved);
        Assert.Equal("msg-1", saved!.Id);
        Assert.Equal("user-1", saved.UserId);
        Assert.Equal("delete", saved.Action);
        Assert.Equal("file", saved.ResourceType);
        Assert.Equal("file-9", saved.ResourceId);
        Assert.Equal("10.0.0.5", saved.IpAddress);
        Assert.Equal("TestAgent", saved.UserAgent);
        Assert.Equal(new DateTime(2026, 1, 2, 3, 4, 5, DateTimeKind.Utc), saved.Timestamp.ToUniversalTime());
        Assert.Equal("cleanup", saved.Details!["reason"]);
        _mockSqs.Verify(s => s.DeleteMessageAsync(QueueUrl, "rh-1", It.IsAny<CancellationToken>()), Times.Once);
    }

    [Fact]
    public async Task ExecuteAsync_ShouldApplyDefaults_WhenAuditFieldsAreMissing()
    {
        SetupQueueUrl();

        AuditEvent? saved = null;
        _mockRepository
            .Setup(r => r.SaveEventAsync(It.IsAny<AuditEvent>()))
            .Callback<AuditEvent>(e => saved = e)
            .Returns(Task.CompletedTask);

        await RunConsumerAsync(new Message { MessageId = "msg-2", ReceiptHandle = "rh-2", Body = "{}" });

        Assert.NotNull(saved);
        Assert.Equal("system", saved!.UserId);
        Assert.Equal("unknown", saved.Action);
        Assert.Equal("unknown", saved.ResourceType);
        Assert.Equal(string.Empty, saved.ResourceId);
        Assert.True(saved.Timestamp <= DateTime.UtcNow);
        Assert.True(saved.Timestamp > DateTime.UtcNow.AddMinutes(-1));
        _mockSqs.Verify(s => s.DeleteMessageAsync(QueueUrl, "rh-2", It.IsAny<CancellationToken>()), Times.Once);
    }

    [Fact]
    public async Task ExecuteAsync_ShouldUnwrapSnsEnvelope_AndRecordFileShareEvent()
    {
        SetupQueueUrl();
        var inner = JsonSerializer.Serialize(new
        {
            eventType = "file_shared",
            fileId = "file-1",
            ownerId = "owner-1",
            sharedWithUserId = "user-2",
            timestamp = new DateTime(2026, 3, 4, 5, 6, 7, DateTimeKind.Utc),
        });
        var envelope = JsonSerializer.Serialize(new { Type = "Notification", Message = inner });

        AuditEvent? saved = null;
        _mockRepository
            .Setup(r => r.SaveEventAsync(It.IsAny<AuditEvent>()))
            .Callback<AuditEvent>(e => saved = e)
            .Returns(Task.CompletedTask);

        await RunConsumerAsync(new Message { MessageId = "msg-3", ReceiptHandle = "rh-3", Body = envelope });

        Assert.NotNull(saved);
        Assert.Equal("share", saved!.Action);
        Assert.Equal("file", saved.ResourceType);
        Assert.Equal("file-1", saved.ResourceId);
        Assert.Equal("owner-1", saved.UserId);
        Assert.Equal("user-2", saved.Details!["sharedWithUserId"]);
        Assert.Equal(new DateTime(2026, 3, 4, 5, 6, 7, DateTimeKind.Utc), saved.Timestamp.ToUniversalTime());
        _mockSqs.Verify(s => s.DeleteMessageAsync(QueueUrl, "rh-3", It.IsAny<CancellationToken>()), Times.Once);
    }

    [Fact]
    public async Task ExecuteAsync_ShouldFallBackToSystemOwner_WhenFileShareFieldsAreNull()
    {
        SetupQueueUrl();
        var body = JsonSerializer.Serialize(new { eventType = "file_shared" });

        AuditEvent? saved = null;
        _mockRepository
            .Setup(r => r.SaveEventAsync(It.IsAny<AuditEvent>()))
            .Callback<AuditEvent>(e => saved = e)
            .Returns(Task.CompletedTask);

        await RunConsumerAsync(new Message { MessageId = "msg-4", ReceiptHandle = "rh-4", Body = body });

        Assert.NotNull(saved);
        Assert.Equal("system", saved!.UserId);
        Assert.Equal(string.Empty, saved.ResourceId);
        Assert.Equal(string.Empty, saved.Details!["sharedWithUserId"]);
        Assert.True(saved.Timestamp <= DateTime.UtcNow);
    }

    [Fact]
    public async Task ExecuteAsync_ShouldDropMessage_WhenBodyDeserializesToNull()
    {
        SetupQueueUrl();

        var envelope = JsonSerializer.Serialize(new { Type = "Notification", Message = "null" });

        await RunConsumerAsync(new Message { MessageId = "msg-5", ReceiptHandle = "rh-5", Body = envelope });

        _mockRepository.Verify(r => r.SaveEventAsync(It.IsAny<AuditEvent>()), Times.Never);
        _mockSqs.Verify(s => s.DeleteMessageAsync(QueueUrl, "rh-5", It.IsAny<CancellationToken>()), Times.Once);
        VerifyLogged(LogLevel.Warning, Times.Once());
    }

    [Fact]
    public async Task ExecuteAsync_ShouldKeepMessage_WhenRepositoryThrows()
    {
        SetupQueueUrl();
        _mockRepository
            .Setup(r => r.SaveEventAsync(It.IsAny<AuditEvent>()))
            .ThrowsAsync(new InvalidOperationException("dynamo down"));

        await RunConsumerAsync(new Message { MessageId = "msg-6", ReceiptHandle = "rh-6", Body = "{}" });

        _mockSqs.Verify(s => s.DeleteMessageAsync(It.IsAny<string>(), It.IsAny<string>(), It.IsAny<CancellationToken>()), Times.Never);
        VerifyLogged(LogLevel.Error, Times.AtLeastOnce());
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

        await RunConsumerAsync(new Message { MessageId = "msg-7", ReceiptHandle = "rh-7", Body = "{}" });

        _mockSqs.Verify(
            s => s.CreateQueueAsync(It.Is<CreateQueueRequest>(r => r.QueueName == QueueName), It.IsAny<CancellationToken>()),
            Times.Once);
        _mockRepository.Verify(r => r.SaveEventAsync(It.IsAny<AuditEvent>()), Times.Once);
    }

    [Fact]
    public async Task ExecuteAsync_ShouldStopWithoutPolling_WhenQueueInitializationFails()
    {
        _mockSqs
            .Setup(s => s.GetQueueUrlAsync(QueueName, It.IsAny<CancellationToken>()))
            .ThrowsAsync(new AmazonSQSException("no credentials"));

        var consumer = CreateConsumer();
        using var cts = new CancellationTokenSource();

        await consumer.StartAsync(cts.Token);
        await consumer.StopAsync(CancellationToken.None);

        _mockSqs.Verify(
            s => s.ReceiveMessageAsync(It.IsAny<ReceiveMessageRequest>(), It.IsAny<CancellationToken>()),
            Times.Never);
        VerifyLogged(LogLevel.Warning, Times.Once());
    }

    [Fact]
    public async Task ExecuteAsync_ShouldLogAndBackOff_WhenReceiveFails()
    {
        SetupQueueUrl();
        var consumer = CreateConsumer();
        using var cts = new CancellationTokenSource();

        _mockSqs
            .Setup(s => s.ReceiveMessageAsync(It.IsAny<ReceiveMessageRequest>(), It.IsAny<CancellationToken>()))
            .Returns<ReceiveMessageRequest, CancellationToken>((_, _) =>
            {
                cts.Cancel();
                throw new AmazonSQSException("receive failed");
            });

        try
        {
            await consumer.StartAsync(cts.Token);
            await consumer.StopAsync(CancellationToken.None);
        }
        catch (OperationCanceledException)
        {
            // the 5s back-off delay observes the stopping token
        }

        _mockRepository.Verify(r => r.SaveEventAsync(It.IsAny<AuditEvent>()), Times.Never);
        VerifyLogged(LogLevel.Error, Times.Once());
    }

    [Fact]
    public async Task ExecuteAsync_ShouldExitLoop_WhenReceiveIsCancelled()
    {
        SetupQueueUrl();
        var consumer = CreateConsumer();
        using var cts = new CancellationTokenSource();

        _mockSqs
            .Setup(s => s.ReceiveMessageAsync(It.IsAny<ReceiveMessageRequest>(), It.IsAny<CancellationToken>()))
            .Returns<ReceiveMessageRequest, CancellationToken>((_, token) =>
            {
                cts.Cancel();
                token.ThrowIfCancellationRequested();
                return Task.FromResult(new ReceiveMessageResponse());
            });

        await consumer.StartAsync(cts.Token);
        await consumer.StopAsync(CancellationToken.None);

        _mockRepository.Verify(r => r.SaveEventAsync(It.IsAny<AuditEvent>()), Times.Never);
        VerifyLogged(LogLevel.Error, Times.Never());
    }

    private SnsConsumer CreateConsumer() =>
        new(_mockSqs.Object, _mockRepository.Object, _options, _mockLogger.Object);

    private void SetupQueueUrl() =>
        _mockSqs
            .Setup(s => s.GetQueueUrlAsync(QueueName, It.IsAny<CancellationToken>()))
            .ReturnsAsync(new GetQueueUrlResponse { QueueUrl = QueueUrl });

    private async Task RunConsumerAsync(params Message[] messages)
    {
        var consumer = CreateConsumer();
        using var cts = new CancellationTokenSource();
        var receiveCount = 0;

        _mockSqs
            .Setup(s => s.ReceiveMessageAsync(It.IsAny<ReceiveMessageRequest>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(() =>
            {
                if (Interlocked.Increment(ref receiveCount) > 1)
                {
                    cts.Cancel();
                    return new ReceiveMessageResponse { Messages = new List<Message>() };
                }

                return new ReceiveMessageResponse { Messages = messages.ToList() };
            });
        _mockSqs
            .Setup(s => s.DeleteMessageAsync(It.IsAny<string>(), It.IsAny<string>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(new DeleteMessageResponse());

        await consumer.StartAsync(cts.Token);
        await consumer.StopAsync(CancellationToken.None);
    }

    private void VerifyLogged(LogLevel level, Times times) =>
        _mockLogger.Verify(
            l => l.Log(
                level,
                It.IsAny<EventId>(),
                It.IsAny<It.IsAnyType>(),
                It.IsAny<Exception>(),
                It.IsAny<Func<It.IsAnyType, Exception?, string>>()),
            times);
}
