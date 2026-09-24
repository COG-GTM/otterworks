using System.Text.Json.Serialization;

namespace OtterWorks.AuditService.Models;

public sealed class ResourceHistory
{
    public string ResourceId { get; set; } = string.Empty;
    public int TotalEvents { get; set; }
    public int Page { get; set; } = 1;
    public int PageSize { get; set; }
    public bool HasMore { get; set; }
    public List<AuditEventResponse> Events { get; set; } = new();

    /// <summary>
    /// Whether any event of this resource — not just the returned page — was
    /// recorded against a file, which decides access when file-service no
    /// longer knows the resource.
    /// </summary>
    [JsonIgnore]
    public bool HasFileEvents { get; set; }
}
