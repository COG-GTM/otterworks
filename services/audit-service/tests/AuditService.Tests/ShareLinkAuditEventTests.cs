using System.Text.Encodings.Web;
using System.Text.Json;
using Amazon.S3;
using Amazon.S3.Model;
using Amazon.SQS;
using Amazon.SQS.Model;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using Moq;
using OtterWorks.AuditService.Config;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

// OTW-69 (OTW-63 US5): folder share-link and sharing policy audit events reach audit-service
// through SNS/SQS, persist as AuditEvents and appear in export.
public class ShareLinkAuditEventTests
{
    private const string FolderId = "5b6a1d6e-2f4f-4a51-9d8e-0b7c3a2e9f10";
    private const string LinkId = "0f8e3c2b-7a6d-4e5f-9b1a-2c3d4e5f6a7b";
    private const string ActorId = "9c1f2e3d-4b5a-6978-8a9b-0c1d2e3f4a5b";

    // Python's json.dumps and Ruby's to_json do not escape '+', so neither do these fixtures.
    private static readonly JsonSerializerOptions PublisherJson = new() { Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping };

    private static string DocumentServiceMessage(
        string eventType, object? oldValue, object? newValue, string? actorId = ActorId, string? auditId = null)
    {
        var payload = new
        {
            eventType,
            auditId = auditId ?? Guid.NewGuid().ToString(),
            actor = new { type = actorId is null ? "system" : "user", id = actorId },
            workspaceId = "default",
            resource = new { type = "folder_share_link", folderId = FolderId, linkId = LinkId },
            oldValue,
            newValue,
            timestamp = "2026-11-10T17:00:00.123456+00:00",
        };
        return JsonSerializer.Serialize(
            new { event_type = eventType, timestamp = "2026-11-10T17:00:01+00:00", payload }, PublisherJson);
    }

    private static string PolicyMessage(string? actorId = ActorId) => JsonSerializer.Serialize(new
    {
        event_type = "folder_share_link.policy_changed",
        timestamp = "2026-11-10T17:00:01Z",
        payload = new
        {
            eventType = "folder_share_link.policy_changed",
            auditId = "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d",
            actor = new { type = "user", id = actorId },
            workspaceId = "default",
            resource = new { type = "sharing_policy", workspaceId = "default" },
            oldValue = new { default_expiry_days = 30, min_expiry_days = 1, max_expiry_days = 90 },
            newValue = new { default_expiry_days = 14, min_expiry_days = 7, max_expiry_days = 60 },
            timestamp = "2026-11-10T17:00:00.5Z",
        },
    });

    private static string SnsEnvelope(string message) =>
        JsonSerializer.Serialize(new { Type = "Notification", Message = message });

    [Fact]
    public void GivenLinkCreatedEvent_WhenMapped_ThenActorWorkspaceResourceValuesAndTimestampArePersisted()
    {
        var body = DocumentServiceMessage(
            "folder_share_link.created", null, new { expires_at = "2026-12-10T17:00:00+00:00" }, auditId: "c0ffee00-0000-4000-8000-000000000001");

        Assert.True(ShareLinkAuditEventMapper.TryMap(body, out var e));

        Assert.Equal("c0ffee00-0000-4000-8000-000000000001", e.Id);
        Assert.Equal(ActorId, e.UserId);
        Assert.Equal("folder_share_link.created", e.Action);
        Assert.Equal("folder_share_link", e.ResourceType);
        Assert.Equal(LinkId, e.ResourceId);
        Assert.Equal("default", e.Details!["workspaceId"]);
        Assert.Equal(FolderId, e.Details["folderId"]);
        Assert.Equal(LinkId, e.Details["linkId"]);
        Assert.Equal("user", e.Details["actorType"]);
        Assert.Equal("null", e.Details["oldValue"]);
        Assert.Equal("{\"expires_at\":\"2026-12-10T17:00:00+00:00\"}", e.Details["newValue"]);
        Assert.Equal(new DateTime(2026, 11, 10, 17, 0, 0, 123, DateTimeKind.Utc).AddTicks(4560), e.Timestamp);
        Assert.Equal(DateTimeKind.Utc, e.Timestamp.Kind);
    }

    [Fact]
    public void GivenLinkUpdatedEvent_WhenMapped_ThenOldAndNewExpiryAreKept()
    {
        var body = DocumentServiceMessage(
            "folder_share_link.updated",
            new { expires_at = "2026-11-20T00:00:00+00:00" },
            new { expires_at = "2026-11-30T00:00:00+00:00" });

        Assert.True(ShareLinkAuditEventMapper.TryMap(body, out var e));

        Assert.Equal("folder_share_link.updated", e.Action);
        Assert.Contains("2026-11-20", e.Details!["oldValue"]);
        Assert.Contains("2026-11-30", e.Details["newValue"]);
    }

    [Fact]
    public void GivenLinkRevokedEvent_WhenMapped_ThenRevokedAtChangeIsKept()
    {
        var body = DocumentServiceMessage(
            "folder_share_link.revoked", new { revoked_at = (string?)null }, new { revoked_at = "2026-11-10T17:00:00+00:00" });

        Assert.True(ShareLinkAuditEventMapper.TryMap(body, out var e));

        Assert.Equal("folder_share_link.revoked", e.Action);
        Assert.Equal("{\"revoked_at\":null}", e.Details!["oldValue"]);
        Assert.Contains("2026-11-10T17:00:00", e.Details["newValue"]);
    }

    [Fact]
    public void GivenLinkExpiredEvent_WhenMapped_ThenActorIsSystem()
    {
        var body = DocumentServiceMessage(
            "folder_share_link.expired",
            new { status = "active", expires_at = "2026-11-10T17:00:00+00:00" },
            new { status = "expired", expires_at = "2026-11-10T17:00:00+00:00" },
            actorId: null);

        Assert.True(ShareLinkAuditEventMapper.TryMap(body, out var e));

        Assert.Equal("folder_share_link.expired", e.Action);
        Assert.Equal("system", e.UserId);
        Assert.Equal("system", e.Details!["actorType"]);
        Assert.Contains("\"expired\"", e.Details["newValue"]);
    }

    [Fact]
    public void GivenPolicyChangedEvent_WhenMapped_ThenOldAndNewDefaultMinMaxAreKept()
    {
        Assert.True(ShareLinkAuditEventMapper.TryMap(PolicyMessage(), out var e));

        Assert.Equal("a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d", e.Id);
        Assert.Equal("folder_share_link.policy_changed", e.Action);
        Assert.Equal("sharing_policy", e.ResourceType);
        Assert.Equal("default", e.ResourceId);
        Assert.Equal(ActorId, e.UserId);
        Assert.False(e.Details!.ContainsKey("linkId"));
        var oldValue = JsonDocument.Parse(e.Details["oldValue"]).RootElement;
        var newValue = JsonDocument.Parse(e.Details["newValue"]).RootElement;
        Assert.Equal(30, oldValue.GetProperty("default_expiry_days").GetInt32());
        Assert.Equal(1, oldValue.GetProperty("min_expiry_days").GetInt32());
        Assert.Equal(90, oldValue.GetProperty("max_expiry_days").GetInt32());
        Assert.Equal(14, newValue.GetProperty("default_expiry_days").GetInt32());
        Assert.Equal(7, newValue.GetProperty("min_expiry_days").GetInt32());
        Assert.Equal(60, newValue.GetProperty("max_expiry_days").GetInt32());
    }

    [Theory]
    [InlineData("{\"eventType\":\"file_shared\",\"fileId\":\"f1\",\"ownerId\":\"u1\"}")]
    [InlineData("{\"event_type\":\"document_created\",\"timestamp\":\"2026-11-10T00:00:00Z\",\"payload\":{\"id\":\"d1\"}}")]
    [InlineData("{\"userId\":\"u1\",\"action\":\"create\",\"resourceType\":\"doc\",\"resourceId\":\"d1\"}")]
    [InlineData("not json")]
    [InlineData("[]")]
    public void GivenOtherOrMalformedMessages_WhenMapped_ThenExistingHandlingIsUsed(string body)
    {
        Assert.False(ShareLinkAuditEventMapper.TryMap(body, out _));
    }

    [Fact]
    public async Task GivenShareLinkEventOnAuditQueue_WhenConsumed_ThenSavedWithAuditIdAndMessageDeleted()
    {
        const string queueUrl = "http://localstack:4566/000000000000/otterworks-audit-events-queue";
        var body = SnsEnvelope(DocumentServiceMessage(
            "folder_share_link.expired",
            new { status = "active", expires_at = "2026-11-10T17:00:00+00:00" },
            new { status = "expired", expires_at = "2026-11-10T17:00:00+00:00" },
            actorId: null,
            auditId: "e1e1e1e1-0000-5000-8000-000000000001"));

        var sqs = new Mock<IAmazonSQS>();
        sqs.Setup(s => s.GetQueueUrlAsync("otterworks-audit-events-queue", It.IsAny<CancellationToken>()))
            .ReturnsAsync(new GetQueueUrlResponse { QueueUrl = queueUrl });
        var delivered = false;
        sqs.Setup(s => s.ReceiveMessageAsync(It.IsAny<ReceiveMessageRequest>(), It.IsAny<CancellationToken>()))
            .Returns(async (ReceiveMessageRequest _, CancellationToken ct) =>
            {
                if (!delivered)
                {
                    delivered = true;
                    return new ReceiveMessageResponse
                    {
                        Messages = { new Message { MessageId = "sqs-1", ReceiptHandle = "rh-1", Body = body } },
                    };
                }

                await Task.Delay(Timeout.Infinite, ct);
                return new ReceiveMessageResponse();
            });
        var deleted = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
        sqs.Setup(s => s.DeleteMessageAsync(queueUrl, It.IsAny<string>(), It.IsAny<CancellationToken>()))
            .Callback((string _, string handle, CancellationToken _) => deleted.TrySetResult(handle))
            .ReturnsAsync(new DeleteMessageResponse());

        var saved = new List<AuditEvent>();
        var repository = new Mock<IAuditRepository>();
        repository.Setup(r => r.SaveEventAsync(It.IsAny<AuditEvent>()))
            .Callback<AuditEvent>(saved.Add)
            .Returns(Task.CompletedTask);

        var consumer = new SnsConsumer(
            sqs.Object, repository.Object, Options.Create(new AwsSettings()), NullLogger<SnsConsumer>.Instance);
        await consumer.StartAsync(CancellationToken.None);
        var handle = await deleted.Task.WaitAsync(TimeSpan.FromSeconds(10));
        await consumer.StopAsync(CancellationToken.None);

        Assert.Equal("rh-1", handle);
        var e = Assert.Single(saved);
        Assert.Equal("e1e1e1e1-0000-5000-8000-000000000001", e.Id);
        Assert.Equal("folder_share_link.expired", e.Action);
        Assert.Equal("system", e.UserId);
        Assert.Equal(LinkId, e.ResourceId);
        Assert.Equal(FolderId, e.Details!["folderId"]);
    }

    [Fact]
    public async Task GivenShareLinkEventsPersisted_WhenExported_ThenEachAppearsInJsonAndCsv()
    {
        var events = new List<AuditEvent>();
        foreach (var body in new[]
                 {
                     DocumentServiceMessage("folder_share_link.created", null, new { expires_at = "2026-12-10T17:00:00+00:00" }),
                     DocumentServiceMessage("folder_share_link.revoked", new { revoked_at = (string?)null }, new { revoked_at = "2026-11-10T17:00:00+00:00" }),
                     PolicyMessage(),
                 })
        {
            Assert.True(ShareLinkAuditEventMapper.TryMap(body, out var e));
            events.Add(e);
        }

        var from = new DateTime(2026, 11, 1, 0, 0, 0, DateTimeKind.Utc);
        var to = new DateTime(2026, 11, 30, 0, 0, 0, DateTimeKind.Utc);
        var repository = new Mock<IAuditRepository>();
        repository.Setup(r => r.GetEventsByDateRangeAsync(from, to)).ReturnsAsync(events);
        var uploads = new List<PutObjectRequest>();
        var s3 = new Mock<IAmazonS3>();
        s3.Setup(s => s.PutObjectAsync(It.IsAny<PutObjectRequest>(), default))
            .Callback<PutObjectRequest, CancellationToken>((req, _) => uploads.Add(req))
            .ReturnsAsync(new PutObjectResponse());
        var archiver = new S3AuditArchiver(
            s3.Object, repository.Object,
            Options.Create(new AwsSettings { S3ArchiveBucket = "audit" }),
            NullLogger<S3AuditArchiver>.Instance);

        Assert.Equal(3, (await archiver.ExportAsync(from, to, "json")).EventCount);
        Assert.Equal(3, (await archiver.ExportAsync(from, to, "csv")).EventCount);

        var json = JsonDocument.Parse(uploads[0].ContentBody).RootElement;
        Assert.Equal(3, json.GetArrayLength());
        var created = json[0];
        Assert.Equal("folder_share_link.created", created.GetProperty("Action").GetString());
        Assert.Equal(LinkId, created.GetProperty("ResourceId").GetString());
        Assert.Equal(FolderId, created.GetProperty("Details").GetProperty("folderId").GetString());
        Assert.Equal("default", created.GetProperty("Details").GetProperty("workspaceId").GetString());
        Assert.Contains("expires_at", created.GetProperty("Details").GetProperty("newValue").GetString());

        var csvLines = uploads[1].ContentBody.TrimEnd().Split('\n');
        Assert.Equal(4, csvLines.Length); // header + one row per event
        Assert.Contains("\"folder_share_link.created\"", csvLines[1]);
        Assert.Contains("\"folder_share_link.revoked\"", csvLines[2]);
        Assert.Contains("\"folder_share_link.policy_changed\"", csvLines[3]);
    }
}
