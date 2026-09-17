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
    private const string QueueUrl = "https://sqs.us-east-1.local/000000000000/otterworks-audit-events-queue";

    private readonly Mock<IAmazonSQS> _sqs = new();
    private readonly Mock<IAuditRepository> _repository = new();
    private readonly Mock<ILogger<SnsConsumer>> _logger = new();

    public SnsConsumerTests()
    {
        _sqs
            .Setup(s => s.GetQueueUrlAsync("otterworks-audit-events-queue", It.IsAny<CancellationToken>()))
            .ReturnsAsync(new GetQueueUrlResponse { QueueUrl = QueueUrl });
    }

    [Fact]
    public async Task ExecuteAsync_StopsWithoutPolling_WhenQueueLookupFails()
    {
        _sqs
            .Setup(s => s.GetQueueUrlAsync(It.IsAny<string>(), It.IsAny<CancellationToken>()))
            .ThrowsAsync(new AmazonSQSException("no sqs here"));

        var consumer = CreateConsumer();
        await consumer.StartAsync(CancellationToken.None);
        await consumer.StopAsync(CancellationToken.None);

        _sqs.Verify(
            s => s.ReceiveMessageAsync(It.IsAny<ReceiveMessageRequest>(), It.IsAny<CancellationToken>()),
            Times.Never);
        VerifyLogged(LogLevel.Warning, "Failed to initialize SQS queue");
    }

    [Fact]
    public async Task ExecuteAsync_CreatesQueueAndPollsIt_WhenQueueDoesNotExist()
    {
        _sqs
            .Setup(s => s.GetQueueUrlAsync(It.IsAny<string>(), It.IsAny<CancellationToken>()))
            .ThrowsAsync(new QueueDoesNotExistException("missing"));
        _sqs
            .Setup(s => s.CreateQueueAsync(
                It.Is<CreateQueueRequest>(r => r.QueueName == "otterworks-audit-events-queue"),
                It.IsAny<CancellationToken>()))
            .ReturnsAsync(new CreateQueueResponse { QueueUrl = QueueUrl });

        var receiveRequests = await RunConsumerAsync();

        _sqs.Verify(
            s => s.CreateQueueAsync(It.IsAny<CreateQueueRequest>(), It.IsAny<CancellationToken>()),
            Times.Once);
        Assert.Equal(QueueUrl, receiveRequests[0].QueueUrl);
        Assert.Equal(10, receiveRequests[0].MaxNumberOfMessages);
        Assert.Equal(20, receiveRequests[0].WaitTimeSeconds);
    }

    [Fact]
    public async Task ProcessMessage_SavesShareEvent_WhenBodyIsAnSnsWrappedFileSharedEvent()
    {
        var timestamp = new DateTime(2026, 4, 1, 10, 30, 0, DateTimeKind.Utc);
        var inner = JsonSerializer.Serialize(new
        {
            eventType = "file_shared",
            fileId = "file-9",
            ownerId = "user-owner",
            sharedWithUserId = "user-guest",
            timestamp,
        });
        var envelope = JsonSerializer.Serialize(new { Type = "Notification", Message = inner });

        AuditEvent? saved = null;
        _repository
            .Setup(r => r.SaveEventAsync(It.IsAny<AuditEvent>()))
            .Callback<AuditEvent>(e => saved = e)
            .Returns(Task.CompletedTask);

        await RunConsumerAsync(SqsMessage("msg-1", envelope, "receipt-1"));

        Assert.NotNull(saved);
        Assert.Equal("msg-1", saved!.Id);
        Assert.Equal("user-owner", saved.UserId);
        Assert.Equal("share", saved.Action);
        Assert.Equal("file", saved.ResourceType);
        Assert.Equal("file-9", saved.ResourceId);
        Assert.Equal("user-guest", saved.Details!["sharedWithUserId"]);
        Assert.Equal(timestamp, saved.Timestamp);
        VerifyMessageDeleted("receipt-1", Times.Once());
    }

    [Fact]
    public async Task ProcessMessage_FallsBackToSystemOwner_WhenShareEventOmitsFields()
    {
        var body = JsonSerializer.Serialize(new { eventType = "file_shared" });
        AuditEvent? saved = null;
        _repository
            .Setup(r => r.SaveEventAsync(It.IsAny<AuditEvent>()))
            .Callback<AuditEvent>(e => saved = e)
            .Returns(Task.CompletedTask);

        var before = DateTime.UtcNow;
        await RunConsumerAsync(SqsMessage("msg-2", body, "receipt-2"));

        Assert.NotNull(saved);
        Assert.Equal("system", saved!.UserId);
        Assert.Equal(string.Empty, saved.ResourceId);
        Assert.Equal(string.Empty, saved.Details!["sharedWithUserId"]);
        Assert.InRange(saved.Timestamp, before, DateTime.UtcNow);
        VerifyMessageDeleted("receipt-2", Times.Once());
    }

    [Fact]
    public async Task ProcessMessage_SavesAuditEvent_WhenBodyIsARawAuditEvent()
    {
        var timestamp = new DateTime(2026, 4, 2, 8, 0, 0, DateTimeKind.Utc);
        var body = JsonSerializer.Serialize(new
        {
            userId = "user-7",
            action = "delete",
            resourceType = "document",
            resourceId = "doc-3",
            details = new Dictionary<string, string> { ["reason"] = "cleanup" },
            ipAddress = "10.1.2.3",
            userAgent = "curl/8.0",
            timestamp,
        });

        AuditEvent? saved = null;
        _repository
            .Setup(r => r.SaveEventAsync(It.IsAny<AuditEvent>()))
            .Callback<AuditEvent>(e => saved = e)
            .Returns(Task.CompletedTask);

        await RunConsumerAsync(SqsMessage("msg-3", body, "receipt-3"));

        Assert.NotNull(saved);
        Assert.Equal("msg-3", saved!.Id);
        Assert.Equal("user-7", saved.UserId);
        Assert.Equal("delete", saved.Action);
        Assert.Equal("document", saved.ResourceType);
        Assert.Equal("doc-3", saved.ResourceId);
        Assert.Equal("cleanup", saved.Details!["reason"]);
        Assert.Equal("10.1.2.3", saved.IpAddress);
        Assert.Equal("curl/8.0", saved.UserAgent);
        Assert.Equal(timestamp, saved.Timestamp);
        VerifyMessageDeleted("receipt-3", Times.Once());
    }

    [Fact]
    public async Task ProcessMessage_AppliesDefaults_WhenAuditEventFieldsAreMissing()
    {
        AuditEvent? saved = null;
        _repository
            .Setup(r => r.SaveEventAsync(It.IsAny<AuditEvent>()))
            .Callback<AuditEvent>(e => saved = e)
            .Returns(Task.CompletedTask);

        var before = DateTime.UtcNow;
        await RunConsumerAsync(SqsMessage("msg-4", "{}", "receipt-4"));

        Assert.NotNull(saved);
        Assert.Equal("system", saved!.UserId);
        Assert.Equal("unknown", saved.Action);
        Assert.Equal("unknown", saved.ResourceType);
        Assert.Equal(string.Empty, saved.ResourceId);
        Assert.Null(saved.Details);
        Assert.InRange(saved.Timestamp, before, DateTime.UtcNow);
        VerifyMessageDeleted("receipt-4", Times.Once());
    }

    [Fact]
    public async Task ProcessMessage_DropsMessage_WhenPayloadDeserializesToNull()
    {
        var envelope = JsonSerializer.Serialize(new { Type = "Notification", Message = "null" });

        await RunConsumerAsync(SqsMessage("msg-5", envelope, "receipt-5"));

        _repository.Verify(r => r.SaveEventAsync(It.IsAny<AuditEvent>()), Times.Never);
        VerifyLogged(LogLevel.Warning, "Failed to deserialize audit event");
        VerifyMessageDeleted("receipt-5", Times.Once());
    }

    /// <summary>
    /// A bare JSON <c>null</c> body escapes the envelope parser: <c>TryParseSnsEnvelope</c> only
    /// guards against <see cref="JsonException"/>, while reading a property off a JSON null throws
    /// <see cref="InvalidOperationException"/>. The message is therefore treated as a processing
    /// failure and left on the queue rather than being dropped as undeserializable.
    /// </summary>
    [Fact]
    public async Task ProcessMessage_KeepsMessage_WhenBodyIsJsonNull()
    {
        await RunConsumerAsync(SqsMessage("msg-10", "null", "receipt-10"));

        _repository.Verify(r => r.SaveEventAsync(It.IsAny<AuditEvent>()), Times.Never);
        VerifyLogged(LogLevel.Error, "Failed to process message msg-10");
        VerifyMessageDeleted("receipt-10", Times.Never());
    }

    [Fact]
    public async Task ProcessMessage_KeepsMessage_WhenBodyIsNotJson()
    {
        await RunConsumerAsync(SqsMessage("msg-6", "this is not json", "receipt-6"));

        _repository.Verify(r => r.SaveEventAsync(It.IsAny<AuditEvent>()), Times.Never);
        VerifyLogged(LogLevel.Error, "Failed to process message msg-6");
        VerifyMessageDeleted("receipt-6", Times.Never());
    }

    [Fact]
    public async Task ProcessMessage_KeepsMessage_WhenRepositoryThrows()
    {
        _repository
            .Setup(r => r.SaveEventAsync(It.IsAny<AuditEvent>()))
            .ThrowsAsync(new InvalidOperationException("dynamo down"));

        await RunConsumerAsync(SqsMessage("msg-7", "{\"action\":\"read\"}", "receipt-7"));

        VerifyLogged(LogLevel.Error, "Failed to process message msg-7");
        VerifyMessageDeleted("receipt-7", Times.Never());
    }

    [Fact]
    public async Task ProcessMessage_HandlesEveryMessageInABatch()
    {
        var saved = new List<AuditEvent>();
        _repository
            .Setup(r => r.SaveEventAsync(It.IsAny<AuditEvent>()))
            .Callback<AuditEvent>(saved.Add)
            .Returns(Task.CompletedTask);

        await RunConsumerAsync(
            SqsMessage("msg-8", "{\"action\":\"read\"}", "receipt-8"),
            SqsMessage("msg-9", "{\"action\":\"update\"}", "receipt-9"));

        Assert.Equal(new[] { "read", "update" }, saved.Select(e => e.Action));
        VerifyMessageDeleted("receipt-8", Times.Once());
        VerifyMessageDeleted("receipt-9", Times.Once());
    }

    [Fact]
    public async Task ExecuteAsync_LogsAndBacksOff_WhenReceiveFails()
    {
        var failed = new TaskCompletionSource();
        _sqs
            .Setup(s => s.ReceiveMessageAsync(It.IsAny<ReceiveMessageRequest>(), It.IsAny<CancellationToken>()))
            .Callback(() => failed.TrySetResult())
            .ThrowsAsync(new AmazonSQSException("throttled"));

        var consumer = CreateConsumer();
        await consumer.StartAsync(CancellationToken.None);
        await failed.Task.WaitAsync(TimeSpan.FromSeconds(10));
        await consumer.StopAsync(CancellationToken.None);

        VerifyLogged(LogLevel.Error, "Error processing SQS messages");
    }

    [Fact]
    public async Task ExecuteAsync_ShutsDownCleanly_WhenStopped()
    {
        await RunConsumerAsync();

        VerifyLogged(LogLevel.Information, "SNS Consumer starting");
        VerifyLogged(LogLevel.Information, "SNS Consumer stopping");
    }

    /// <summary>
    /// Runs the consumer until the given batch has been polled and processed, then stops it.
    /// The second poll parks until the host shuts the consumer down, which keeps the test
    /// free of sleeps and of live SQS long-polling.
    /// </summary>
    private async Task<List<ReceiveMessageRequest>> RunConsumerAsync(params Message[] messages)
    {
        var requests = new List<ReceiveMessageRequest>();
        var batchPolled = new TaskCompletionSource();
        var polls = 0;

        _sqs
            .Setup(s => s.ReceiveMessageAsync(It.IsAny<ReceiveMessageRequest>(), It.IsAny<CancellationToken>()))
            .Returns((ReceiveMessageRequest request, CancellationToken ct) =>
            {
                requests.Add(request);
                if (Interlocked.Increment(ref polls) == 1)
                    return Task.FromResult(new ReceiveMessageResponse { Messages = messages.ToList() });

                batchPolled.TrySetResult();
                return ParkUntilShutdownAsync(ct);
            });

        var consumer = CreateConsumer();
        await consumer.StartAsync(CancellationToken.None);
        await batchPolled.Task.WaitAsync(TimeSpan.FromSeconds(10));
        await consumer.StopAsync(CancellationToken.None);

        return requests;
    }

    private static async Task<ReceiveMessageResponse> ParkUntilShutdownAsync(CancellationToken ct)
    {
        await Task.Delay(Timeout.Infinite, ct);
        return new ReceiveMessageResponse();
    }

    private SnsConsumer CreateConsumer() => new(
        _sqs.Object,
        _repository.Object,
        Options.Create(new AwsSettings()),
        _logger.Object);

    private static Message SqsMessage(string id, string body, string receiptHandle) => new()
    {
        MessageId = id,
        Body = body,
        ReceiptHandle = receiptHandle,
    };

    private void VerifyMessageDeleted(string receiptHandle, Times times) =>
        _sqs.Verify(
            s => s.DeleteMessageAsync(QueueUrl, receiptHandle, It.IsAny<CancellationToken>()),
            times);

    private void VerifyLogged(LogLevel level, string messageFragment) =>
        _logger.Verify(
            l => l.Log(
                level,
                It.IsAny<EventId>(),
                It.Is<It.IsAnyType>((state, _) => state.ToString()!.Contains(messageFragment)),
                It.IsAny<Exception?>(),
                It.IsAny<Func<It.IsAnyType, Exception?, string>>()),
            Times.AtLeastOnce);
}
