using System.Net;
using System.Text.Json;

namespace OtterWorks.AuditService.Services;

/// <summary>
/// Resolves file ownership and shares from file-service to decide who may
/// read a file's audit history.
/// </summary>
public sealed class FileResourceAccessAuthorizer : IResourceAccessAuthorizer
{
    private readonly HttpClient _httpClient;
    private readonly ILogger<FileResourceAccessAuthorizer> _logger;

    public FileResourceAccessAuthorizer(HttpClient httpClient, ILogger<FileResourceAccessAuthorizer> logger)
    {
        _httpClient = httpClient;
        _logger = logger;
    }

    public async Task<bool> CanReadHistoryAsync(string resourceId, string? userId, CancellationToken ct = default)
    {
        HttpResponseMessage response;
        try
        {
            response = await _httpClient.GetAsync($"/api/v1/files/{resourceId}", ct);
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException)
        {
            _logger.LogWarning(ex, "file-service unreachable while authorizing history for {ResourceId}", resourceId);
            return false;
        }

        // Anything that is not a known file (documents, folders, synthetic
        // resource ids) is outside this access rule.
        if (response.StatusCode is HttpStatusCode.NotFound or HttpStatusCode.BadRequest)
        {
            return true;
        }

        if (!response.IsSuccessStatusCode)
        {
            _logger.LogWarning(
                "file-service returned {Status} while authorizing history for {ResourceId}",
                (int)response.StatusCode,
                resourceId);
            return false;
        }

        if (string.IsNullOrWhiteSpace(userId))
        {
            return false;
        }

        var body = await response.Content.ReadAsStringAsync(ct);
        using var doc = JsonDocument.Parse(body);
        var root = doc.RootElement;

        if (root.TryGetProperty("owner_id", out var owner) &&
            string.Equals(owner.GetString(), userId, StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        if (root.TryGetProperty("shared_with", out var shares) && shares.ValueKind == JsonValueKind.Array)
        {
            foreach (var share in shares.EnumerateArray())
            {
                if (share.TryGetProperty("shared_with", out var sharedWith) &&
                    string.Equals(sharedWith.GetString(), userId, StringComparison.OrdinalIgnoreCase))
                {
                    return true;
                }
            }
        }

        return false;
    }
}
