using System.Text;
using System.Text.Json;
using Amazon.S3;
using Amazon.S3.Model;
using Microsoft.Extensions.Logging;
using Microsoft.Extensions.Options;
using Moq;
using OtterWorks.AuditService.Config;
using OtterWorks.AuditService.Services;

namespace AuditService.Tests;

public class S3AuditArchiverTests
{
    private readonly Mock<IAmazonS3> _mockS3;
    private readonly Mock<IAuditRepository> _mockRepository;
    private readonly Mock<ILogger<S3AuditArchiver>> _mockLogger;
    private readonly IOptions<AwsSettings> _options;
    private readonly S3AuditArchiver _archiver;

    public S3AuditArchiverTests()
    {
        _mockS3 = new Mock<IAmazonS3>();
        _mockRepository = new Mock<IAuditRepository>();
        _mockLogger = new Mock<ILogger<S3AuditArchiver>>();
        _options = Options.Create(new AwsSettings
        {
            S3ArchiveBucket = "test-archive-bucket",
            Region = "us-east-1",
        });

        _archiver = new S3AuditArchiver(_mockS3.Object, _mockRepository.Object, _options, _mockLogger.Object);
    }

    [Fact]
    public async Task ExportAsync_WithJsonFormat_ShouldUploadJsonToS3()
    {
        var from = DateTime.UtcNow.AddDays(-7);
        var to = DateTime.UtcNow;
        var events = new List<AuditEvent>
        {
            new() { Id = "e1", UserId = "u1", Action = "create", ResourceType = "doc", ResourceId = "d1", Timestamp = DateTime.UtcNow },
        };

        _mockRepository.Setup(r => r.GetEventsByDateRangeAsync(from, to)).ReturnsAsync(events);
        _mockS3.Setup(s => s.PutObjectAsync(It.IsAny<PutObjectRequest>(), default)).ReturnsAsync(new PutObjectResponse());

        var result = await _archiver.ExportAsync(from, to, "json");

        Assert.Equal("json", result.Format);
        Assert.Equal(1, result.EventCount);
        Assert.Contains("test-archive-bucket", result.DownloadUrl);
        Assert.Contains(".json", result.DownloadUrl);

        _mockS3.Verify(s => s.PutObjectAsync(It.Is<PutObjectRequest>(req =>
            req.BucketName == "test-archive-bucket" &&
            req.ContentType == "application/json"),
            default), Times.Once);
    }

    [Fact]
    public async Task ExportAsync_WithCsvFormat_ShouldUploadCsvToS3()
    {
        var from = DateTime.UtcNow.AddDays(-7);
        var to = DateTime.UtcNow;
        var events = new List<AuditEvent>
        {
            new() { Id = "e1", UserId = "u1", Action = "create", ResourceType = "doc", ResourceId = "d1", Timestamp = DateTime.UtcNow },
        };

        _mockRepository.Setup(r => r.GetEventsByDateRangeAsync(from, to)).ReturnsAsync(events);
        _mockS3.Setup(s => s.PutObjectAsync(It.IsAny<PutObjectRequest>(), default)).ReturnsAsync(new PutObjectResponse());

        var result = await _archiver.ExportAsync(from, to, "csv");

        Assert.Equal("csv", result.Format);
        Assert.Equal(1, result.EventCount);
        Assert.Contains(".csv", result.DownloadUrl);

        _mockS3.Verify(s => s.PutObjectAsync(It.Is<PutObjectRequest>(req =>
            req.ContentType == "text/csv"),
            default), Times.Once);
    }

    [Fact]
    public async Task ArchiveOldEventsAsync_WithEvents_ShouldUploadToGlacierAndDelete()
    {
        var olderThan = DateTime.UtcNow.AddDays(-90);
        var events = new List<AuditEvent>
        {
            new() { Id = "old-1", UserId = "u1", Action = "create", ResourceType = "doc", ResourceId = "d1", Timestamp = olderThan.AddDays(-10) },
            new() { Id = "old-2", UserId = "u2", Action = "update", ResourceType = "doc", ResourceId = "d2", Timestamp = olderThan.AddDays(-5) },
        };

        _mockRepository.Setup(r => r.GetEventsByDateRangeAsync(DateTime.MinValue, olderThan)).ReturnsAsync(events);
        _mockS3.Setup(s => s.PutObjectAsync(It.IsAny<PutObjectRequest>(), default)).ReturnsAsync(new PutObjectResponse());
        _mockRepository.Setup(r => r.DeleteEventsAsync(It.IsAny<IEnumerable<string>>())).ReturnsAsync(2);

        var result = await _archiver.ArchiveOldEventsAsync(olderThan);

        Assert.Equal(2, result.ArchivedCount);
        Assert.Contains("test-archive-bucket", result.S3Location);
        Assert.Equal("GLACIER", result.StorageClass);

        _mockS3.Verify(s => s.PutObjectAsync(It.Is<PutObjectRequest>(req =>
            req.StorageClass == S3StorageClass.Glacier &&
            req.BucketName == "test-archive-bucket"),
            default), Times.Once);

        _mockRepository.Verify(r => r.DeleteEventsAsync(
            It.Is<IEnumerable<string>>(ids => ids.Count() == 2)), Times.Once);
    }

    [Fact]
    public async Task ArchiveOldEventsAsync_WithNoEvents_ShouldReturnZeroCount()
    {
        var olderThan = DateTime.UtcNow.AddDays(-90);

        _mockRepository
            .Setup(r => r.GetEventsByDateRangeAsync(DateTime.MinValue, olderThan))
            .ReturnsAsync(new List<AuditEvent>());

        var result = await _archiver.ArchiveOldEventsAsync(olderThan);

        Assert.Equal(0, result.ArchivedCount);
        Assert.Empty(result.S3Location);

        _mockS3.Verify(s => s.PutObjectAsync(It.IsAny<PutObjectRequest>(), default), Times.Never);
        _mockRepository.Verify(r => r.DeleteEventsAsync(It.IsAny<IEnumerable<string>>()), Times.Never);
    }

    private const string ExpectedCsvHeader =
        "Id,Timestamp,UserId,Action,ResourceType,ResourceId,IpAddress,UserAgent,WorkspaceId,OldValue,NewValue";

    private async Task<string> ExportAndCaptureBodyAsync(List<AuditEvent> events, string format)
    {
        var from = DateTime.UtcNow.AddDays(-7);
        var to = DateTime.UtcNow;
        string? body = null;

        _mockRepository.Setup(r => r.GetEventsByDateRangeAsync(from, to)).ReturnsAsync(events);
        _mockS3.Setup(s => s.PutObjectAsync(It.IsAny<PutObjectRequest>(), default))
            .Callback<PutObjectRequest, CancellationToken>((req, _) => body = req.ContentBody)
            .ReturnsAsync(new PutObjectResponse());

        await _archiver.ExportAsync(from, to, format);

        Assert.NotNull(body);
        return body!;
    }

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
                if (c == '"' && i + 1 < csv.Length && csv[i + 1] == '"')
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
                row.Add(field.ToString());
                field.Clear();
            }
            else if (c == '\n' || c == '\r')
            {
                if (c == '\r' && i + 1 < csv.Length && csv[i + 1] == '\n')
                    i++;
                row.Add(field.ToString());
                field.Clear();
                rows.Add(row);
                row = new List<string>();
            }
            else
            {
                field.Append(c);
            }
        }

        if (field.Length > 0 || row.Count > 0)
        {
            row.Add(field.ToString());
            rows.Add(row);
        }

        return rows;
    }

    private static JsonElement Json(string json) => JsonDocument.Parse(json).RootElement.Clone();

    [Fact]
    public async Task ExportAsync_Csv_HeaderHasExistingColumnsPlusWorkspaceIdOldValueNewValue()
    {
        var body = await ExportAndCaptureBodyAsync(new List<AuditEvent>(), "csv");

        var header = body.Split(Environment.NewLine)[0];
        Assert.Equal(ExpectedCsvHeader, header);
    }

    [Fact]
    public async Task ExportAsync_Csv_WritesWorkspaceIdAndCompactJsonOldAndNewValues()
    {
        var ts = new DateTime(2026, 11, 9, 12, 0, 0, DateTimeKind.Utc);
        var events = new List<AuditEvent>
        {
            new()
            {
                Id = "e1", UserId = "u1", Action = "share_link_updated", ResourceType = "share_link", ResourceId = "l1",
                IpAddress = "10.0.0.1", UserAgent = "Agent/1.0", Timestamp = ts,
                WorkspaceId = "default",
                OldValue = Json("{ \"expires_at\" : \"2026-12-01T00:00:00Z\" }"),
                NewValue = Json("{\n  \"expires_at\": null,\n  \"never\": true\n}"),
            },
        };

        var rows = ParseCsv(await ExportAndCaptureBodyAsync(events, "csv"));

        Assert.Equal(2, rows.Count);
        Assert.Equal(ExpectedCsvHeader.Split(','), rows[0]);
        Assert.Equal(
            new[]
            {
                "e1", ts.ToString("O"), "u1", "share_link_updated", "share_link", "l1", "10.0.0.1", "Agent/1.0",
                "default", "{\"expires_at\":\"2026-12-01T00:00:00Z\"}", "{\"expires_at\":null,\"never\":true}",
            },
            rows[1]);
    }

    [Fact]
    public async Task ExportAsync_Csv_EscapesQuotesCommasAndNewlines()
    {
        var events = new List<AuditEvent>
        {
            new()
            {
                Id = "e1", UserId = "u1", Action = "update", ResourceType = "doc", ResourceId = "d1", Timestamp = DateTime.UtcNow,
                UserAgent = "Mozilla/5.0 (X11, \"Linux\")",
                WorkspaceId = "ws,\"quoted\"\nline2",
                OldValue = Json("{\"title\":\"a, \\\"b\\\"\\nc\"}"),
                NewValue = Json("\"plain, \\\"text\\\"\""),
            },
        };

        var body = await ExportAndCaptureBodyAsync(events, "csv");
        var rows = ParseCsv(body);

        Assert.Contains("\"ws,\"\"quoted\"\"\nline2\"", body);
        Assert.Contains("\"{\"\"title\"\":\"\"a, \\\"\"b\\\"\"\\nc\"\"}\"", body);
        Assert.Equal(2, rows.Count);
        Assert.Equal(11, rows[1].Count);
        Assert.Equal("Mozilla/5.0 (X11, \"Linux\")", rows[1][7]);
        Assert.Equal("ws,\"quoted\"\nline2", rows[1][8]);
        Assert.Equal("a, \"b\"\nc", JsonDocument.Parse(rows[1][9]).RootElement.GetProperty("title").GetString());
        Assert.Equal("plain, \"text\"", JsonDocument.Parse(rows[1][10]).RootElement.GetString());
    }

    [Fact]
    public async Task ExportAsync_Csv_LeavesNewColumnsEmptyForLegacyEvents()
    {
        var events = new List<AuditEvent>
        {
            new() { Id = "e1", UserId = "u1", Action = "create", ResourceType = "doc", ResourceId = "d1", Timestamp = DateTime.UtcNow },
        };

        var rows = ParseCsv(await ExportAndCaptureBodyAsync(events, "csv"));

        Assert.Equal(11, rows[1].Count);
        Assert.Equal(string.Empty, rows[1][8]);
        Assert.Equal(string.Empty, rows[1][9]);
        Assert.Equal(string.Empty, rows[1][10]);
    }

    [Fact]
    public async Task ExportAsync_Json_KeepsExistingFieldsAndAddsNullableNewFields()
    {
        var ts = new DateTime(2026, 11, 9, 12, 0, 0, DateTimeKind.Utc);
        var events = new List<AuditEvent>
        {
            new()
            {
                Id = "legacy", UserId = "u1", Action = "create", ResourceType = "doc", ResourceId = "d1", Timestamp = ts,
                IpAddress = "10.0.0.1", UserAgent = "Agent", Details = new Dictionary<string, string> { ["k"] = "v" },
            },
            new()
            {
                Id = "share", UserId = "u2", Action = "share_link_created", ResourceType = "share_link", ResourceId = "l1", Timestamp = ts,
                WorkspaceId = "default", NewValue = Json("{\"expires_at\":\"2026-12-09T12:00:00Z\"}"),
            },
        };

        var body = await ExportAndCaptureBodyAsync(events, "json");
        using var doc = JsonDocument.Parse(body);
        var items = doc.RootElement.EnumerateArray().ToList();

        Assert.Equal(2, items.Count);
        var legacy = items[0];
        Assert.Equal(
            new[] { "Id", "UserId", "Action", "ResourceType", "ResourceId", "Details", "IpAddress", "UserAgent", "Timestamp", "WorkspaceId", "OldValue", "NewValue" },
            legacy.EnumerateObject().Select(p => p.Name).ToArray());
        Assert.Equal("legacy", legacy.GetProperty("Id").GetString());
        Assert.Equal("v", legacy.GetProperty("Details").GetProperty("k").GetString());
        Assert.Equal(ts, legacy.GetProperty("Timestamp").GetDateTime());
        Assert.Equal(JsonValueKind.Null, legacy.GetProperty("WorkspaceId").ValueKind);
        Assert.Equal(JsonValueKind.Null, legacy.GetProperty("OldValue").ValueKind);
        Assert.Equal(JsonValueKind.Null, legacy.GetProperty("NewValue").ValueKind);

        var share = items[1];
        Assert.Equal("default", share.GetProperty("WorkspaceId").GetString());
        Assert.Equal(JsonValueKind.Null, share.GetProperty("OldValue").ValueKind);
        Assert.Equal("2026-12-09T12:00:00Z", share.GetProperty("NewValue").GetProperty("expires_at").GetString());
    }
}
