using Amazon.SQS;
using Amazon.SQS.Model;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Moq;
using OtterWorks.AuditService.Config;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

public class SnsConsumerTests
{
    private const string QueueName = "otterworks-audit-events-queue";
    private const string QueueUrl = "http://sqs.local/000000000000/otterworks-audit-events-queue";

    private readonly Mock<IAmazonSQS> _sqs = new();
    private readonly Mock<IAuditRepository> _repository = new();
    private readonly List<AuditEvent> _saved = new();
    private readonly TestableSnsConsumer _consumer;

    public SnsConsumerTests()
    {
        _repository.Setup(r => r.SaveEventAsync(It.IsAny<AuditEvent>()))
            .Callback<AuditEvent>(_saved.Add)
            .Returns(Task.CompletedTask);
        _sqs.Setup(s => s.DeleteMessageAsync(It.IsAny<string>(), It.IsAny<string>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(new DeleteMessageResponse());
        _consumer = new TestableSnsConsumer(
            _sqs.Object,
            _repository.Object,
            Options.Create(new AwsSettings()),
            NullLogger<SnsConsumer>.Instance);
    }

    private sealed class TestableSnsConsumer : SnsConsumer
    {
        public TestableSnsConsumer(IAmazonSQS sqs, IAuditRepository repo, IOptions<AwsSettings> settings, Microsoft.Extensions.Logging.ILogger<SnsConsumer> logger)
            : base(sqs, repo, settings, logger)
        {
        }

        public Task RunAsync(CancellationToken ct) => ExecuteAsync(ct);
    }

    private void SetupQueueUrl() =>
        _sqs.Setup(s => s.GetQueueUrlAsync(QueueName, It.IsAny<CancellationToken>()))
            .ReturnsAsync(new GetQueueUrlResponse { QueueUrl = QueueUrl });

    private async Task RunWithMessagesAsync(params Message[] messages)
    {
        SetupQueueUrl();
        using var cts = new CancellationTokenSource();
        var calls = 0;
        _sqs.Setup(s => s.ReceiveMessageAsync(It.IsAny<ReceiveMessageRequest>(), It.IsAny<CancellationToken>()))
            .Returns<ReceiveMessageRequest, CancellationToken>((req, ct) =>
            {
                Assert.Equal(QueueUrl, req.QueueUrl);
                Assert.Equal(10, req.MaxNumberOfMessages);
                Assert.Equal(20, req.WaitTimeSeconds);
                if (calls++ == 0)
                    return Task.FromResult(new ReceiveMessageResponse { Messages = messages.ToList() });
                cts.Cancel();
                throw new OperationCanceledException(cts.Token);
            });

        await _consumer.RunAsync(cts.Token);
    }

    private static Message Msg(string id, string body) =>
        new() { MessageId = id, ReceiptHandle = $"rh-{id}", Body = body };

    private void VerifyDeleted(string id, Times times) =>
        _sqs.Verify(s => s.DeleteMessageAsync(QueueUrl, $"rh-{id}", It.IsAny<CancellationToken>()), times);

    [Fact]
    public async Task SnsEnvelopeWithAuditEvent_IsSavedAndDeleted()
    {
        var inner = """{"userId":"u1","action":"update","resourceType":"document","resourceId":"d1","details":{"k":"v"},"ipAddress":"10.0.0.1","userAgent":"ua","timestamp":"2026-01-02T03:04:05Z"}""";
        var envelope = System.Text.Json.JsonSerializer.Serialize(new { Type = "Notification", Message = inner });

        await RunWithMessagesAsync(Msg("m1", envelope));

        var e = Assert.Single(_saved);
        Assert.Equal("m1", e.Id);
        Assert.Equal("u1", e.UserId);
        Assert.Equal("update", e.Action);
        Assert.Equal("document", e.ResourceType);
        Assert.Equal("d1", e.ResourceId);
        Assert.Equal("v", e.Details!["k"]);
        Assert.Equal("10.0.0.1", e.IpAddress);
        Assert.Equal("ua", e.UserAgent);
        Assert.Equal(new DateTime(2026, 1, 2, 3, 4, 5, DateTimeKind.Utc), e.Timestamp.ToUniversalTime());
        VerifyDeleted("m1", Times.Once());
    }

    [Fact]
    public async Task RawAuditEventWithoutFields_UsesDefaults()
    {
        var before = DateTime.UtcNow;

        await RunWithMessagesAsync(Msg("m2", "{}"));

        var e = Assert.Single(_saved);
        Assert.Equal("system", e.UserId);
        Assert.Equal("unknown", e.Action);
        Assert.Equal("unknown", e.ResourceType);
        Assert.Equal(string.Empty, e.ResourceId);
        Assert.True(e.Timestamp >= before);
        VerifyDeleted("m2", Times.Once());
    }

    [Fact]
    public async Task FileSharedEvent_IsMappedToShareAuditEvent()
    {
        var inner = """{"eventType":"file_shared","fileId":"f1","ownerId":"o1","sharedWithUserId":"u2","timestamp":"2026-03-04T05:06:07Z"}""";
        var envelope = System.Text.Json.JsonSerializer.Serialize(new { Message = inner });

        await RunWithMessagesAsync(Msg("m3", envelope));

        var e = Assert.Single(_saved);
        Assert.Equal("m3", e.Id);
        Assert.Equal("o1", e.UserId);
        Assert.Equal("share", e.Action);
        Assert.Equal("file", e.ResourceType);
        Assert.Equal("f1", e.ResourceId);
        Assert.Equal("u2", e.Details!["sharedWithUserId"]);
        Assert.Equal(new DateTime(2026, 3, 4, 5, 6, 7, DateTimeKind.Utc), e.Timestamp.ToUniversalTime());
        VerifyDeleted("m3", Times.Once());
    }

    [Fact]
    public async Task FileSharedEventWithMissingFields_UsesDefaults()
    {
        await RunWithMessagesAsync(Msg("m4", """{"eventType":"file_shared"}"""));

        var e = Assert.Single(_saved);
        Assert.Equal("system", e.UserId);
        Assert.Equal(string.Empty, e.ResourceId);
        Assert.Equal(string.Empty, e.Details!["sharedWithUserId"]);
        VerifyDeleted("m4", Times.Once());
    }

    [Fact]
    public async Task SnsEnvelopeWithNullMessage_IsDeletedWithoutSaving()
    {
        await RunWithMessagesAsync(Msg("m5", """{"Message":"null"}"""));

        Assert.Empty(_saved);
        VerifyDeleted("m5", Times.Once());
    }

    [Fact]
    public async Task MalformedJson_IsNotSavedOrDeleted()
    {
        await RunWithMessagesAsync(Msg("m6", "not json"));

        Assert.Empty(_saved);
        VerifyDeleted("m6", Times.Never());
    }

    [Fact]
    public async Task RepositoryFailure_LeavesMessageOnQueueAndContinues()
    {
        _repository.Setup(r => r.SaveEventAsync(It.Is<AuditEvent>(e => e.Id == "bad")))
            .ThrowsAsync(new InvalidOperationException("dynamo down"));

        await RunWithMessagesAsync(
            Msg("bad", """{"userId":"u1"}"""),
            Msg("good", """{"userId":"u2"}"""));

        VerifyDeleted("bad", Times.Never());
        VerifyDeleted("good", Times.Once());
        Assert.Equal("u2", Assert.Single(_saved).UserId);
    }

    [Fact]
    public async Task MissingQueue_IsCreated()
    {
        _sqs.Setup(s => s.GetQueueUrlAsync(QueueName, It.IsAny<CancellationToken>()))
            .ThrowsAsync(new QueueDoesNotExistException("missing"));
        _sqs.Setup(s => s.CreateQueueAsync(It.Is<CreateQueueRequest>(r => r.QueueName == QueueName), It.IsAny<CancellationToken>()))
            .ReturnsAsync(new CreateQueueResponse { QueueUrl = "created-url" });
        using var cts = new CancellationTokenSource();
        string? polledUrl = null;
        _sqs.Setup(s => s.ReceiveMessageAsync(It.IsAny<ReceiveMessageRequest>(), It.IsAny<CancellationToken>()))
            .Returns<ReceiveMessageRequest, CancellationToken>((req, _) =>
            {
                polledUrl = req.QueueUrl;
                cts.Cancel();
                throw new OperationCanceledException(cts.Token);
            });

        await _consumer.RunAsync(cts.Token);

        Assert.Equal("created-url", polledUrl);
    }

    [Fact]
    public async Task QueueInitFailure_StopsWithoutPolling()
    {
        _sqs.Setup(s => s.GetQueueUrlAsync(QueueName, It.IsAny<CancellationToken>()))
            .ThrowsAsync(new AmazonSQSException("no credentials"));

        await _consumer.RunAsync(CancellationToken.None);

        _sqs.Verify(s => s.ReceiveMessageAsync(It.IsAny<ReceiveMessageRequest>(), It.IsAny<CancellationToken>()), Times.Never);
    }

    [Fact]
    public async Task ReceiveFailure_BacksOffUntilCancelled()
    {
        SetupQueueUrl();
        using var cts = new CancellationTokenSource();
        _sqs.Setup(s => s.ReceiveMessageAsync(It.IsAny<ReceiveMessageRequest>(), It.IsAny<CancellationToken>()))
            .Returns<ReceiveMessageRequest, CancellationToken>((_, _) =>
            {
                cts.Cancel();
                throw new AmazonSQSException("throttled");
            });

        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => _consumer.RunAsync(cts.Token));
        _sqs.Verify(s => s.ReceiveMessageAsync(It.IsAny<ReceiveMessageRequest>(), It.IsAny<CancellationToken>()), Times.Once);
    }

    [Fact]
    public async Task AlreadyCancelledToken_ExitsLoopImmediately()
    {
        SetupQueueUrl();
        using var cts = new CancellationTokenSource();
        cts.Cancel();

        await _consumer.RunAsync(cts.Token);

        _sqs.Verify(s => s.ReceiveMessageAsync(It.IsAny<ReceiveMessageRequest>(), It.IsAny<CancellationToken>()), Times.Never);
    }
}
