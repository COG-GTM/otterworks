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
using OtterWorks.AuditService.Controllers;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

// OTW-74 AC9: audit history for share links is exportable as CSV with the AC8 fields
// (actor, workspace, resource, old value, new value, timestamp).
public class ShareLinkCsvExportTests
{
    private static readonly DateTime From = new(2026, 11, 1, 0, 0, 0, DateTimeKind.Utc);
    private static readonly DateTime To = new(2026, 11, 30, 0, 0, 0, DateTimeKind.Utc);

    private readonly Mock<IAmazonS3> _mockS3 = new();
    private readonly Mock<IAuditRepository> _mockRepository = new();
    private readonly S3AuditArchiver _archiver;
    private PutObjectRequest? _uploaded;

    public ShareLinkCsvExportTests()
    {
        var options = Options.Create(new AwsSettings { S3ArchiveBucket = "test-archive-bucket", Region = "us-east-1" });
        _archiver = new S3AuditArchiver(_mockS3.Object, _mockRepository.Object, options, Mock.Of<ILogger<S3AuditArchiver>>());
        _mockS3
            .Setup(s => s.PutObjectAsync(It.IsAny<PutObjectRequest>(), default))
            .Callback<PutObjectRequest, CancellationToken>((req, _) => _uploaded = req)
            .ReturnsAsync(new PutObjectResponse());
    }

    private static AuditEvent ShareEvent(string id, string action, string resourceType, string resourceId,
        string? oldValue, string? newValue, string workspace = "ws-acme", string actor = "user-owner")
    {
        return new AuditEvent
        {
            Id = id,
            UserId = actor,
            Action = action,
            ResourceType = resourceType,
            ResourceId = resourceId,
            Timestamp = new DateTime(2026, 11, 10, 12, 0, 0, DateTimeKind.Utc),
            Details = new Dictionary<string, string>
            {
                ["workspace_id"] = workspace,
                ["old_value"] = oldValue!,
                ["new_value"] = newValue!,
                ["timestamp"] = "2026-11-10T11:59:59Z",
            },
        };
    }

    private static List<AuditEvent> MixedEvents() => new()
    {
        ShareEvent("e1", "share_link.created", "share_link", "link-1", null, "2026-11-17T12:00:00Z"),
        ShareEvent("e2", "share_link.expiry_changed", "share_link", "link-1", "2026-11-17T12:00:00Z", "2026-11-24T12:00:00Z"),
        ShareEvent("e3", "share_link.expired", "share_link", "link-1", "active", "expired", actor: "system"),
        ShareEvent("e4", "share_policy.updated", "share_policy", "ws-acme", "{\"default_days\":7}", "{\"default_days\":14}"),
        new() { Id = "e5", UserId = "user-2", Action = "create", ResourceType = "document", ResourceId = "doc-9", Timestamp = new DateTime(2026, 11, 10, 9, 0, 0, DateTimeKind.Utc) },
    };

    private async Task<List<Dictionary<string, string>>> ExportCsv(IReadOnlyCollection<string>? resourceTypes)
    {
        _mockRepository.Setup(r => r.GetEventsByDateRangeAsync(From, To)).ReturnsAsync(MixedEvents());
        await _archiver.ExportAsync(From, To, "csv", resourceTypes);
        Assert.NotNull(_uploaded);
        Assert.Equal("text/csv", _uploaded!.ContentType);

        var rows = CsvParser.Parse(_uploaded.ContentBody);
        var header = rows[0];
        return rows.Skip(1)
            .Select(r => header.Zip(r).ToDictionary(p => p.First, p => p.Second))
            .ToList();
    }

    [Fact]
    public void AC9_CsvHeader_KeepsExistingColumnsAndAppendsShareLinkFields()
    {
        var header = CsvParser.Parse(AuditCsvWriter.Write(Array.Empty<AuditEvent>()))[0];

        Assert.Equal(
            new[] { "Id", "Timestamp", "UserId", "Action", "ResourceType", "ResourceId", "IpAddress", "UserAgent" },
            header.Take(8));
        Assert.Equal(new[] { "WorkspaceId", "OldValue", "NewValue", "EventTimestamp" }, header.Skip(8));
    }

    [Fact]
    public async Task AC9_CsvExport_ContainsEveryShareLinkEventWithAc8Fields()
    {
        var rows = await ExportCsv(null);

        Assert.Equal(5, rows.Count);

        var expiryChanged = rows.Single(r => r["Id"] == "e2");
        Assert.Equal("user-owner", expiryChanged["UserId"]);
        Assert.Equal("share_link.expiry_changed", expiryChanged["Action"]);
        Assert.Equal("ws-acme", expiryChanged["WorkspaceId"]);
        Assert.Equal("share_link", expiryChanged["ResourceType"]);
        Assert.Equal("link-1", expiryChanged["ResourceId"]);
        Assert.Equal("2026-11-17T12:00:00Z", expiryChanged["OldValue"]);
        Assert.Equal("2026-11-24T12:00:00Z", expiryChanged["NewValue"]);
        Assert.Equal("2026-11-10T11:59:59Z", expiryChanged["EventTimestamp"]);
        Assert.Equal("2026-11-10T12:00:00.0000000Z", expiryChanged["Timestamp"]);

        Assert.Equal(
            new[] { "share_link.created", "share_link.expiry_changed", "share_link.expired", "share_policy.updated" },
            rows.Where(r => r["ResourceType"] is "share_link" or "share_policy").Select(r => r["Action"]));
    }

    [Fact]
    public async Task AC9_CsvExport_CreatedEventWithNoOldValue_ExportsEmptyOldValue()
    {
        var rows = await ExportCsv(null);

        var created = rows.Single(r => r["Id"] == "e1");
        Assert.Equal(string.Empty, created["OldValue"]);
        Assert.Equal("2026-11-17T12:00:00Z", created["NewValue"]);
    }

    [Fact]
    public async Task AC9_CsvExport_ShareLinkFilter_ExportsOnlyShareLinkAndPolicyEvents()
    {
        _mockRepository.Setup(r => r.GetEventsByDateRangeAsync(From, To)).ReturnsAsync(MixedEvents());

        var result = await _archiver.ExportAsync(From, To, "csv", new[] { "share_link", "share_policy" });

        Assert.Equal(4, result.EventCount);
        Assert.Equal(new[] { "share_link", "share_policy" }, result.ResourceTypes);
        var rows = CsvParser.Parse(_uploaded!.ContentBody).Skip(1).ToList();
        Assert.Equal(new[] { "e1", "e2", "e3", "e4" }, rows.Select(r => r[0]));
    }

    [Fact]
    public async Task AC9_CsvExport_ResourceTypeFilter_IsCaseInsensitive()
    {
        _mockRepository.Setup(r => r.GetEventsByDateRangeAsync(From, To)).ReturnsAsync(MixedEvents());

        var result = await _archiver.ExportAsync(From, To, "csv", new[] { "SHARE_POLICY" });

        Assert.Equal(1, result.EventCount);
        Assert.Contains("share_policy.updated", _uploaded!.ContentBody);
    }

    [Fact]
    public async Task AC9_CsvExport_NonShareEvents_KeepExistingColumnsAndLeaveNewOnesEmpty()
    {
        var rows = await ExportCsv(null);

        var doc = rows.Single(r => r["Id"] == "e5");
        Assert.Equal("user-2", doc["UserId"]);
        Assert.Equal("document", doc["ResourceType"]);
        Assert.Equal(string.Empty, doc["WorkspaceId"]);
        Assert.Equal(string.Empty, doc["OldValue"]);
        Assert.Equal(string.Empty, doc["NewValue"]);
    }

    [Fact]
    public void AC9_Csv_EscapesCommasQuotesAndNewlines()
    {
        var evt = ShareEvent("e1", "share_policy.updated", "share_policy", "ws-acme",
            "{\"min_days\":1,\"max_days\":30}", "line one\r\nline \"two\", three");
        evt.UserAgent = "Mozilla/5.0 (X11, Linux)";

        var csv = AuditCsvWriter.Write(new[] { evt });
        var rows = CsvParser.Parse(csv);

        Assert.Equal(2, rows.Count);
        Assert.All(rows, r => Assert.Equal(AuditCsvWriter.Columns.Length, r.Count));
        Assert.Equal("{\"min_days\":1,\"max_days\":30}", rows[1][9]);
        Assert.Equal("line one\r\nline \"two\", three", rows[1][10]);
        Assert.Equal("Mozilla/5.0 (X11, Linux)", rows[1][7]);
        Assert.Contains("\"{\"\"min_days\"\":1,\"\"max_days\"\":30}\"", csv);
    }

    [Theory]
    [InlineData("=HYPERLINK(\"http://x\")", "'=HYPERLINK(\"http://x\")")]
    [InlineData("+cmd", "'+cmd")]
    [InlineData("@SUM(A1)", "'@SUM(A1)")]
    [InlineData("-2+3", "'-2+3")]
    [InlineData("-7", "-7")]
    [InlineData("7d", "7d")]
    [InlineData("\n=HYPERLINK(\"http://x\")", "'\n=HYPERLINK(\"http://x\")")]
    [InlineData("  =1+1", "'  =1+1")]
    [InlineData(" -7", " -7")]
    public void AC9_Csv_NeutralisesSpreadsheetFormulaValues(string value, string expected)
    {
        var evt = ShareEvent("e1", "share_link.expiry_changed", "share_link", "link-1", value, "x");

        var rows = CsvParser.Parse(AuditCsvWriter.Write(new[] { evt }));

        Assert.Equal(expected, rows[1][9]);
    }

    [Fact]
    public void AC9_Csv_AcceptsCamelCaseDetailKeys()
    {
        var evt = new AuditEvent
        {
            Id = "e1",
            UserId = "u1",
            Action = "share_link.created",
            ResourceType = "share_link",
            ResourceId = "l1",
            Details = new Dictionary<string, string> { ["workspaceId"] = "ws-1", ["oldValue"] = "a", ["newValue"] = "b" },
        };

        var row = CsvParser.Parse(AuditCsvWriter.Write(new[] { evt }))[1];

        Assert.Equal(new[] { "ws-1", "a", "b" }, row.Skip(8).Take(3));
    }

    [Fact]
    public async Task AC9_JsonExport_IsUnchangedAndCarriesShareLinkDetails()
    {
        _mockRepository.Setup(r => r.GetEventsByDateRangeAsync(From, To)).ReturnsAsync(MixedEvents());

        var result = await _archiver.ExportAsync(From, To, "json", null);

        Assert.Equal(5, result.EventCount);
        Assert.Null(result.ResourceTypes);
        Assert.Equal("application/json", _uploaded!.ContentType);
        var events = JsonSerializer.Deserialize<List<AuditEvent>>(_uploaded.ContentBody)!;
        Assert.Equal("ws-acme", events.Single(e => e.Id == "e2").Details!["workspace_id"]);
    }

    [Theory]
    [InlineData(null, null)]
    [InlineData("", null)]
    [InlineData(" , ", null)]
    [InlineData("share_link", new[] { "share_link" })]
    [InlineData("share_link, share_policy,share_link", new[] { "share_link", "share_policy" })]
    public void AC9_ParseResourceTypes_SplitsCommaSeparatedFilter(string? input, string[]? expected)
    {
        var result = AuditController.ParseResourceTypes(input);

        if (expected is null)
            Assert.Null(result);
        else
            Assert.Equal(expected, result);
    }

    [Theory]
    [InlineData(null, "share_link")]
    [InlineData("", "share_link")]
    [InlineData("  ", "share_link")]
    public void AC9_ParseResourceTypes_FallsBackToSnakeCaseAliasWhenCamelCaseIsBlank(string? camel, string snake)
    {
        Assert.Equal(new[] { "share_link" }, AuditController.ParseResourceTypes(camel, snake));
    }

    [Fact]
    public void AC9_ParseResourceTypes_PrefersCamelCaseWhenBothAreSet()
    {
        Assert.Equal(new[] { "share_policy" }, AuditController.ParseResourceTypes("share_policy", "share_link"));
    }

    [Fact]
    public async Task AC9_SaveEvent_WithNullDetailValue_StoresDynamoNull()
    {
        var dynamo = new Mock<IAmazonDynamoDB>();
        dynamo.Setup(d => d.PutItemAsync(It.IsAny<PutItemRequest>(), default)).ReturnsAsync(new PutItemResponse());
        var repo = new DynamoDbAuditRepository(dynamo.Object,
            Options.Create(new AwsSettings { DynamoDbTable = "t", Region = "us-east-1" }),
            Mock.Of<ILogger<DynamoDbAuditRepository>>());

        await repo.SaveEventAsync(ShareEvent("e1", "share_link.created", "share_link", "link-1", null, "2026-11-17T12:00:00Z"));

        dynamo.Verify(d => d.PutItemAsync(It.Is<PutItemRequest>(req =>
            req.Item["Details"].M["old_value"].NULL &&
            req.Item["Details"].M["new_value"].S == "2026-11-17T12:00:00Z"), default), Times.Once);
    }

    private static class CsvParser
    {
        public static List<List<string>> Parse(string csv)
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
                else if (c == '\r') { }
                else if (c == '\n') { row.Add(field.ToString()); field.Clear(); rows.Add(row); row = new List<string>(); }
                else field.Append(c);
            }

            if (field.Length > 0 || row.Count > 0) { row.Add(field.ToString()); rows.Add(row); }
            return rows;
        }
    }
}
