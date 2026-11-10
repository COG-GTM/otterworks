using System.Text;
using System.Text.Json;
using Amazon.DynamoDBv2;
using Amazon.DynamoDBv2.Model;
using Amazon.S3;
using Amazon.S3.Model;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Moq;
using OtterWorks.AuditService.Config;
using OtterWorks.AuditService.Models;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

// OTW-47 (parent OTW-41): audit CSV export carries WorkspaceId, OldValue and NewValue.
public class AuditCsvExportColumnsTests
{
    private static readonly string[] ExpectedHeader =
    {
        "Id", "Timestamp", "UserId", "Action", "ResourceType", "ResourceId",
        "IpAddress", "UserAgent", "WorkspaceId", "OldValue", "NewValue",
    };

    private readonly Mock<IAmazonS3> _mockS3 = new();
    private readonly Mock<IAuditRepository> _mockRepository = new();
    private readonly S3AuditArchiver _archiver;
    private string? _uploadedBody;

    public AuditCsvExportColumnsTests()
    {
        var options = Options.Create(new AwsSettings { S3ArchiveBucket = "test-archive-bucket", Region = "us-east-1" });
        _archiver = new S3AuditArchiver(_mockS3.Object, _mockRepository.Object, options, new Mock<ILogger<S3AuditArchiver>>().Object);
        _mockS3
            .Setup(s => s.PutObjectAsync(It.IsAny<PutObjectRequest>(), default))
            .Callback<PutObjectRequest, CancellationToken>((req, _) => _uploadedBody = req.ContentBody)
            .ReturnsAsync(new PutObjectResponse());
    }

    private async Task<string> ExportAsync(string format, params AuditEvent[] events)
    {
        var from = new DateTime(2026, 11, 1, 0, 0, 0, DateTimeKind.Utc);
        var to = from.AddDays(7);
        _mockRepository.Setup(r => r.GetEventsByDateRangeAsync(from, to)).ReturnsAsync(events.ToList());
        await _archiver.ExportAsync(from, to, format);
        Assert.NotNull(_uploadedBody);
        return _uploadedBody!;
    }

    private static AuditEvent ShareLinkExpiryChanged() => new()
    {
        Id = "evt-1",
        UserId = "user-1",
        Action = "share_link_expiry_changed",
        ResourceType = "folder",
        ResourceId = "folder-1",
        IpAddress = "10.0.0.1",
        UserAgent = "Agent/1.0",
        WorkspaceId = "ws-42",
        OldValue = "{\"expires_in_days\":30}",
        NewValue = "{\"expires_in_days\":7}",
        Timestamp = new DateTime(2026, 11, 3, 12, 0, 0, DateTimeKind.Utc),
    };

    // Minimal RFC 4180 parser so assertions check what a spreadsheet would actually read.
    private static List<List<string>> ParseCsv(string csv)
    {
        var rows = new List<List<string>>();
        var row = new List<string>();
        var field = new StringBuilder();
        var inQuotes = false;
        for (var i = 0; i < csv.Length; i++)
        {
            var c = csv[i];
            if (inQuotes)
            {
                if (c == '"' && i + 1 < csv.Length && csv[i + 1] == '"') { field.Append('"'); i++; }
                else if (c == '"') inQuotes = false;
                else field.Append(c);
            }
            else if (c == '"') inQuotes = true;
            else if (c == ',') { row.Add(field.ToString()); field.Clear(); }
            else if (c == '\n' || c == '\r')
            {
                if (c == '\r' && i + 1 < csv.Length && csv[i + 1] == '\n') i++;
                row.Add(field.ToString()); field.Clear();
                rows.Add(row); row = new List<string>();
            }
            else field.Append(c);
        }

        if (field.Length > 0 || row.Count > 0) { row.Add(field.ToString()); rows.Add(row); }
        return rows;
    }

    // Given a compliance reviewer, When they export audit history as CSV,
    // Then the header has WorkspaceId, OldValue, NewValue after the existing columns.
    [Fact]
    public async Task CsvExport_HeaderIncludesNewColumnsAfterExistingOnes()
    {
        var csv = await ExportAsync("csv", ShareLinkExpiryChanged());

        var rows = ParseCsv(csv);
        Assert.Equal(ExpectedHeader, rows[0]);
    }

    // Given a compliance reviewer, When they export audit history as CSV,
    // Then each row carries the event's WorkspaceId, OldValue and NewValue.
    [Fact]
    public async Task CsvExport_RowContainsWorkspaceIdOldValueAndNewValue()
    {
        var csv = await ExportAsync("csv", ShareLinkExpiryChanged());

        var rows = ParseCsv(csv);
        Assert.Equal(2, rows.Count);
        var row = rows[1];
        Assert.Equal(ExpectedHeader.Length, row.Count);
        Assert.Equal("evt-1", row[0]);
        Assert.Equal("2026-11-03T12:00:00.0000000Z", row[1]);
        Assert.Equal("share_link_expiry_changed", row[3]);
        Assert.Equal("Agent/1.0", row[7]);
        Assert.Equal("ws-42", row[8]);
        Assert.Equal("{\"expires_in_days\":30}", row[9]);
        Assert.Equal("{\"expires_in_days\":7}", row[10]);
    }

    // Given an older event without the new fields, When exported as CSV,
    // Then the new columns are present but empty.
    [Fact]
    public async Task CsvExport_LegacyEventWithoutNewFields_HasEmptyNewColumns()
    {
        var legacy = new AuditEvent { Id = "old", UserId = "u", Action = "create", ResourceType = "file", ResourceId = "f", Timestamp = DateTime.UtcNow };

        var rows = ParseCsv(await ExportAsync("csv", legacy));

        Assert.Equal(ExpectedHeader.Length, rows[1].Count);
        Assert.Equal(new[] { string.Empty, string.Empty, string.Empty }, rows[1].Skip(8));
    }

    // Given values containing quotes, commas or newlines, When exported as CSV,
    // Then they are quoted and escaped so each field round-trips intact.
    [Fact]
    public async Task CsvExport_EscapesQuotesCommasAndNewlines()
    {
        var tricky = ShareLinkExpiryChanged();
        tricky.WorkspaceId = "ws,\"quoted\"";
        tricky.OldValue = "{\"name\":\"Q3, \\\"final\\\"\",\"note\":\"line1\nline2\"}";
        tricky.NewValue = "a\r\nb,\"c\"";
        tricky.UserAgent = "Mozilla/5.0 (X11, \"Linux\")";

        var csv = await ExportAsync("csv", tricky);

        Assert.Contains("\"ws,\"\"quoted\"\"\"", csv);
        var rows = ParseCsv(csv);
        Assert.Equal(2, rows.Count);
        Assert.Equal(ExpectedHeader.Length, rows[1].Count);
        Assert.Equal(tricky.UserAgent, rows[1][7]);
        Assert.Equal(tricky.WorkspaceId, rows[1][8]);
        Assert.Equal(tricky.OldValue, rows[1][9]);
        Assert.Equal(tricky.NewValue.Replace("\r\n", "\n"), rows[1][10].Replace("\r\n", "\n"));
    }

    // Given a compliance reviewer, When they export as JSON,
    // Then the output keeps its existing shape and also carries the new fields.
    [Fact]
    public async Task JsonExport_CarriesNewFieldsAndKeepsExistingOnes()
    {
        var json = await ExportAsync("json", ShareLinkExpiryChanged());

        using var doc = JsonDocument.Parse(json);
        var item = doc.RootElement[0];
        Assert.Equal("evt-1", item.GetProperty("Id").GetString());
        Assert.Equal("user-1", item.GetProperty("UserId").GetString());
        Assert.Equal("folder", item.GetProperty("ResourceType").GetString());
        Assert.Equal("Agent/1.0", item.GetProperty("UserAgent").GetString());
        Assert.Equal("ws-42", item.GetProperty("WorkspaceId").GetString());
        Assert.Equal("{\"expires_in_days\":30}", item.GetProperty("OldValue").GetString());
        Assert.Equal("{\"expires_in_days\":7}", item.GetProperty("NewValue").GetString());
    }

    // Given a service records an audit event via the REST API with the new fields,
    // When it is saved, Then they are persisted and returned.
    [Fact]
    public async Task RecordEventAsync_PersistsAndReturnsNewFields()
    {
        var options = Options.Create(new AwsSettings { DynamoDbTable = "t", S3ArchiveBucket = "b", Region = "us-east-1" });
        var service = new OtterWorks.AuditService.Services.AuditService(
            _mockRepository.Object, new Mock<IAuditArchiver>().Object, options,
            new Mock<ILogger<OtterWorks.AuditService.Services.AuditService>>().Object);

        var response = await service.RecordEventAsync(new AuditEventRequest
        {
            UserId = "u",
            Action = "workspace_share_policy_changed",
            ResourceType = "workspace",
            ResourceId = "ws-42",
            WorkspaceId = "ws-42",
            OldValue = "{\"default_days\":30}",
            NewValue = "{\"default_days\":14}",
        });

        Assert.Equal("ws-42", response.WorkspaceId);
        Assert.Equal("{\"default_days\":30}", response.OldValue);
        Assert.Equal("{\"default_days\":14}", response.NewValue);
        _mockRepository.Verify(r => r.SaveEventAsync(It.Is<AuditEvent>(e =>
            e.WorkspaceId == "ws-42" && e.OldValue == "{\"default_days\":30}" && e.NewValue == "{\"default_days\":14}")), Times.Once);
    }

    // Given an event with the new fields, When saved to and read back from DynamoDB,
    // Then the fields round-trip so the CSV export can include them.
    [Fact]
    public async Task DynamoDbRepository_RoundTripsNewFields()
    {
        var dynamo = new Mock<IAmazonDynamoDB>();
        var options = Options.Create(new AwsSettings { DynamoDbTable = "t", Region = "us-east-1" });
        var repo = new DynamoDbAuditRepository(dynamo.Object, options, new Mock<ILogger<DynamoDbAuditRepository>>().Object);
        Dictionary<string, AttributeValue>? saved = null;
        dynamo.Setup(d => d.PutItemAsync(It.IsAny<PutItemRequest>(), default))
            .Callback<PutItemRequest, CancellationToken>((req, _) => saved = req.Item)
            .ReturnsAsync(new PutItemResponse());

        await repo.SaveEventAsync(ShareLinkExpiryChanged());

        Assert.NotNull(saved);
        Assert.Equal("ws-42", saved!["WorkspaceId"].S);
        Assert.Equal("{\"expires_in_days\":30}", saved["OldValue"].S);
        Assert.Equal("{\"expires_in_days\":7}", saved["NewValue"].S);

        dynamo.Setup(d => d.GetItemAsync(It.IsAny<GetItemRequest>(), default))
            .ReturnsAsync(new GetItemResponse { Item = saved });
        var loaded = await repo.GetEventAsync("evt-1");

        Assert.NotNull(loaded);
        Assert.Equal("ws-42", loaded!.WorkspaceId);
        Assert.Equal("{\"expires_in_days\":30}", loaded.OldValue);
        Assert.Equal("{\"expires_in_days\":7}", loaded.NewValue);
    }

    // Given an event published on SNS with camelCase fields and pre-serialized JSON strings,
    // When the consumer deserializes it, Then the new fields are mapped.
    [Fact]
    public void SnsConsumer_MapsCamelCaseFieldsWithStringValues()
    {
        var body = """
            {"userId":"u","action":"share_link_created","resourceType":"folder","resourceId":"f",
             "workspaceId":"ws-42","oldValue":null,"newValue":"{\"expires_at\":\"2026-12-01T00:00:00Z\"}"}
            """;

        var entity = SnsConsumer.MapAuditEventMessage(body, "msg-1");

        Assert.NotNull(entity);
        Assert.Equal("msg-1", entity!.Id);
        Assert.Equal("ws-42", entity.WorkspaceId);
        Assert.Null(entity.OldValue);
        Assert.Equal("{\"expires_at\":\"2026-12-01T00:00:00Z\"}", entity.NewValue);
    }

    // Given an event published by a Python service with snake_case fields and raw JSON objects,
    // When the consumer deserializes it, Then the values are stored as serialized JSON strings.
    [Fact]
    public void SnsConsumer_MapsSnakeCaseFieldsWithObjectValues()
    {
        var body = """
            {"user_id":"u","action":"share_link_expiry_changed","resource_type":"folder","resource_id":"f",
             "workspace_id":"ws-42","old_value":{"expires_in_days":30},"new_value":{"expires_in_days":7}}
            """;

        var entity = SnsConsumer.MapAuditEventMessage(body, "msg-2");

        Assert.NotNull(entity);
        Assert.Equal("ws-42", entity!.WorkspaceId);
        Assert.Equal("{\"expires_in_days\":30}", entity.OldValue);
        Assert.Equal("{\"expires_in_days\":7}", entity.NewValue);
    }

    // Given an existing publisher that does not send the new fields, When consumed,
    // Then the event is still mapped and the new fields are null.
    [Fact]
    public void SnsConsumer_LegacyMessageWithoutNewFields_LeavesThemNull()
    {
        var entity = SnsConsumer.MapAuditEventMessage(
            """{"userId":"u","action":"create","resourceType":"file","resourceId":"f"}""", "msg-3");

        Assert.NotNull(entity);
        Assert.Equal("create", entity!.Action);
        Assert.Null(entity.WorkspaceId);
        Assert.Null(entity.OldValue);
        Assert.Null(entity.NewValue);
    }
}
