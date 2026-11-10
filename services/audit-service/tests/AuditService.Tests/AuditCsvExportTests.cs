using System.Text;
using System.Text.Json;
using Amazon.S3;
using Amazon.S3.Model;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Moq;
using OtterWorks.AuditService.Config;
using OtterWorks.AuditService.Controllers;
using OtterWorks.AuditService.Models;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

// OTW-70 / OTW-63 US5: CSV export for the audit-service export endpoint.
public class AuditCsvExportTests
{
    private static readonly DateTime From = new(2026, 11, 1, 0, 0, 0, DateTimeKind.Utc);
    private static readonly DateTime To = new(2026, 11, 10, 0, 0, 0, DateTimeKind.Utc);

    private readonly Mock<IAmazonS3> _mockS3 = new();
    private readonly Mock<IAuditRepository> _mockRepository = new();
    private readonly List<PutObjectRequest> _uploads = new();
    private readonly S3AuditArchiver _archiver;

    public AuditCsvExportTests()
    {
        _mockS3
            .Setup(s => s.PutObjectAsync(It.IsAny<PutObjectRequest>(), It.IsAny<CancellationToken>()))
            .Callback<PutObjectRequest, CancellationToken>((req, _) => _uploads.Add(req))
            .ReturnsAsync(new PutObjectResponse());

        _archiver = new S3AuditArchiver(
            _mockS3.Object,
            _mockRepository.Object,
            Options.Create(new AwsSettings { S3ArchiveBucket = "test-archive-bucket", Region = "us-east-1" }),
            new Mock<ILogger<S3AuditArchiver>>().Object);
    }

    private static List<AuditEvent> SampleEvents() => new()
    {
        new()
        {
            Id = "e1", UserId = "u1", Action = "create", ResourceType = "folder", ResourceId = "f1",
            Details = new Dictionary<string, string> { ["link_id"] = "l1", ["expires_at"] = "2026-12-01T00:00:00Z" },
            IpAddress = "10.0.0.1", UserAgent = "curl/8.0",
            Timestamp = new DateTime(2026, 11, 2, 9, 30, 0, DateTimeKind.Utc),
        },
        new()
        {
            Id = "e2", UserId = "u2", Action = "update", ResourceType = "folder", ResourceId = "f1",
            Timestamp = new DateTime(2026, 11, 3, 14, 5, 6, 789, DateTimeKind.Utc),
        },
        new()
        {
            Id = "e3", UserId = "u1", Action = "delete", ResourceType = "folder", ResourceId = "f2",
            UserAgent = "Mozilla/5.0 (X11, Linux) \"quoted\"",
            Details = new Dictionary<string, string> { ["note"] = "line one\r\nline two, with comma" },
            Timestamp = new DateTime(2026, 11, 4, 0, 0, 0, DateTimeKind.Utc),
        },
    };

    private async Task<PutObjectRequest> ExportAsync(List<AuditEvent> events, string format)
    {
        _mockRepository.Setup(r => r.GetEventsByDateRangeAsync(From, To)).ReturnsAsync(events);
        await _archiver.ExportAsync(From, To, format);
        return _uploads.Last();
    }

    // Scenario (US5): Given I request an audit export with format=csv for a date range,
    // Then I get a CSV with a header row and one row per event.
    [Fact]
    public async Task GivenCsvExportForDateRange_ThenCsvHasHeaderRowAndOneRowPerEvent()
    {
        var events = SampleEvents();

        var upload = await ExportAsync(events, "csv");
        var records = ParseCsv(upload.ContentBody);

        Assert.Equal(events.Count + 1, records.Count);
        Assert.Equal(
            new[] { "Id", "UserId", "Action", "ResourceType", "ResourceId", "Details", "IpAddress", "UserAgent", "Timestamp" },
            records[0]);
        Assert.Equal(events.Select(e => e.Id), records.Skip(1).Select(r => r[0]));
        Assert.All(records, r => Assert.Equal(records[0].Count, r.Count));
    }

    // Scenario (US5): ... Then the CSV has the same fields as the JSON export.
    [Fact]
    public async Task GivenCsvExport_ThenColumnsAndValuesMatchTheJsonExport()
    {
        var events = SampleEvents();

        var csv = ParseCsv((await ExportAsync(events, "csv")).ContentBody);
        using var json = JsonDocument.Parse((await ExportAsync(events, "json")).ContentBody);
        var jsonEvents = json.RootElement.EnumerateArray().ToList();

        Assert.Equal(jsonEvents[0].EnumerateObject().Select(p => p.Name), csv[0]);
        Assert.Equal(jsonEvents.Count, csv.Count - 1);

        for (var row = 0; row < jsonEvents.Count; row++)
        {
            var expected = csv[0].Select(column => jsonEvents[row].GetProperty(column) switch
            {
                { ValueKind: JsonValueKind.Null } => string.Empty,
                { ValueKind: JsonValueKind.String } v => v.GetString(),
                var v => JsonSerializer.Serialize(v),
            });
            Assert.Equal(expected, csv[row + 1]);
        }
    }

    // Scenario (US5): CSV uses RFC 4180 escaping for commas, double quotes and line breaks.
    [Fact]
    public async Task GivenFieldsWithCommasQuotesAndLineBreaks_ThenCsvEscapesThemPerRfc4180()
    {
        var events = SampleEvents();

        var body = (await ExportAsync(events, "csv")).ContentBody;
        var records = ParseCsv(body);
        var e3 = records.Single(r => r[0] == "e3");

        Assert.Contains("\"Mozilla/5.0 (X11, Linux) \"\"quoted\"\"\"", body);
        Assert.Equal("Mozilla/5.0 (X11, Linux) \"quoted\"", e3[7]);
        Assert.Equal(
            "line one\r\nline two, with comma",
            JsonSerializer.Deserialize<Dictionary<string, string>>(e3[5])!["note"]);
    }

    [Theory]
    [InlineData("plain", "plain")]
    [InlineData("", "")]
    [InlineData("a,b", "\"a,b\"")]
    [InlineData("say \"hi\"", "\"say \"\"hi\"\"\"")]
    [InlineData("line1\nline2", "\"line1\nline2\"")]
    [InlineData("line1\r\nline2", "\"line1\r\nline2\"")]
    public void EscapeField_FollowsRfc4180(string value, string expected)
    {
        Assert.Equal(expected, AuditCsvWriter.EscapeField(value));
    }

    // Scenario (US5): records are CRLF-terminated (RFC 4180 section 2.1).
    [Fact]
    public async Task GivenCsvExport_ThenEveryRecordEndsWithCrlf()
    {
        var events = SampleEvents().Take(2).ToList();

        var body = (await ExportAsync(events, "csv")).ContentBody;

        Assert.EndsWith("\r\n", body);
        Assert.Equal(3, body.Split("\r\n", StringSplitOptions.RemoveEmptyEntries).Length);
        Assert.DoesNotContain("\n", body.Replace("\r\n", string.Empty));
    }

    // Scenario (US5): nullable fields are empty cells; Details is the same JSON object as the JSON export.
    [Fact]
    public async Task GivenEventWithoutOptionalFields_ThenCellsAreEmptyAndDetailsIsJson()
    {
        var events = SampleEvents();

        var records = ParseCsv((await ExportAsync(events, "csv")).ContentBody);
        var header = records[0];
        var e1 = records.Single(r => r[0] == "e1");
        var e2 = records.Single(r => r[0] == "e2");

        Assert.Equal(string.Empty, e2[header.IndexOf("Details")]);
        Assert.Equal(string.Empty, e2[header.IndexOf("IpAddress")]);
        Assert.Equal(string.Empty, e2[header.IndexOf("UserAgent")]);
        Assert.Equal("2026-11-03T14:05:06.789Z", e2[header.IndexOf("Timestamp")]);
        Assert.Equal("{\"link_id\":\"l1\",\"expires_at\":\"2026-12-01T00:00:00Z\"}", e1[header.IndexOf("Details")]);
    }

    // Scenario (US5): the CSV export is stored with the CSV content type and extension.
    [Fact]
    public async Task GivenCsvExport_ThenObjectHasCsvContentTypeAndExtension()
    {
        var upload = await ExportAsync(SampleEvents(), "csv");

        Assert.Equal("text/csv; charset=utf-8", upload.ContentType);
        Assert.EndsWith(".csv", upload.Key);
        Assert.Equal("test-archive-bucket", upload.BucketName);
    }

    // Scenario (US5): an empty date range still yields a CSV with the header row.
    [Fact]
    public async Task GivenNoEventsInRange_ThenCsvContainsOnlyTheHeaderRow()
    {
        _mockRepository.Setup(r => r.GetEventsByDateRangeAsync(From, To)).ReturnsAsync(new List<AuditEvent>());

        var result = await _archiver.ExportAsync(From, To, "csv");
        var records = ParseCsv(_uploads.Single().ContentBody);

        Assert.Equal(0, result.EventCount);
        Assert.Single(records);
        Assert.Equal("Id", records[0][0]);
    }

    // Scenario (US5): Given the existing JSON export, Then its behaviour is unchanged.
    [Fact]
    public async Task GivenJsonExport_ThenBehaviourIsUnchanged()
    {
        var events = SampleEvents();

        var upload = await ExportAsync(events, "json");

        Assert.Equal("application/json", upload.ContentType);
        Assert.EndsWith(".json", upload.Key);
        Assert.Equal(
            JsonSerializer.Serialize(events, new JsonSerializerOptions { WriteIndented = true }),
            upload.ContentBody);
    }

    // Scenario (US5): Given I request format=csv on the export endpoint, Then a CSV export is produced.
    [Theory]
    [InlineData("csv")]
    [InlineData("CSV")]
    public async Task GivenFormatCsvOnEndpoint_ThenReturns200AndRequestsCsvExport(string format)
    {
        var service = new Mock<IAuditService>();
        service.Setup(s => s.ExportAsync(From, To, format))
            .ReturnsAsync(new ExportResult { Format = format, EventCount = 3 });

        var result = await AuditController.ExportAuditLog(format, From, To, service.Object);

        Assert.Equal(StatusCodes.Status200OK, ((IStatusCodeHttpResult)result).StatusCode);
        service.Verify(s => s.ExportAsync(From, To, format), Times.Once);
    }

    // Scenario (US5): Given the existing JSON export (default format), Then its behaviour is unchanged.
    [Fact]
    public async Task GivenNoFormatOnEndpoint_ThenDefaultsToJsonExport()
    {
        var service = new Mock<IAuditService>();
        service.Setup(s => s.ExportAsync(From, To, "json")).ReturnsAsync(new ExportResult());

        var result = await AuditController.ExportAuditLog(null, From, To, service.Object);

        Assert.Equal(StatusCodes.Status200OK, ((IStatusCodeHttpResult)result).StatusCode);
        service.Verify(s => s.ExportAsync(From, To, "json"), Times.Once);
    }

    // Scenario (OTW-70): unsupported formats return 400 and no export is produced.
    [Theory]
    [InlineData("xml")]
    [InlineData("tsv")]
    [InlineData("")]
    public async Task GivenUnsupportedFormatOnEndpoint_ThenReturns400(string format)
    {
        var service = new Mock<IAuditService>();

        var result = await AuditController.ExportAuditLog(format, From, To, service.Object);

        Assert.Equal(StatusCodes.Status400BadRequest, ((IStatusCodeHttpResult)result).StatusCode);
        service.Verify(s => s.ExportAsync(It.IsAny<DateTime>(), It.IsAny<DateTime>(), It.IsAny<string>()), Times.Never);
    }

    // Minimal RFC 4180 reader used to verify the writer's output independently of it.
    private static List<List<string>> ParseCsv(string text)
    {
        var records = new List<List<string>>();
        var record = new List<string>();
        var field = new StringBuilder();
        var inQuotes = false;

        for (var i = 0; i < text.Length; i++)
        {
            var c = text[i];
            if (inQuotes)
            {
                if (c == '"' && i + 1 < text.Length && text[i + 1] == '"')
                {
                    field.Append('"');
                    i++;
                }
                else if (c == '"')
                {
                    inQuotes = false;
                }
                else
                {
                    field.Append(c);
                }
            }
            else if (c == '"')
            {
                inQuotes = true;
            }
            else if (c == ',')
            {
                record.Add(field.ToString());
                field.Clear();
            }
            else if (c == '\r' && i + 1 < text.Length && text[i + 1] == '\n')
            {
                record.Add(field.ToString());
                field.Clear();
                records.Add(record);
                record = new List<string>();
                i++;
            }
            else
            {
                field.Append(c);
            }
        }

        if (field.Length > 0 || record.Count > 0)
        {
            record.Add(field.ToString());
            records.Add(record);
        }

        return records;
    }
}
