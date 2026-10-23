namespace OtterWorks.AuditService.Services;

public class AuditEvent
{
    public string Id { get; set; } = string.Empty;
    public string UserId { get; set; } = string.Empty;
    public string Action { get; set; } = string.Empty; // create, read, update, delete, share, login, logout
    public string ResourceType { get; set; } = string.Empty; // file, document, folder, user, permission
    public string ResourceId { get; set; } = string.Empty;
    public Dictionary<string, string>? Details { get; set; }
    public string? IpAddress { get; set; }
    public string? UserAgent { get; set; }
    public DateTime Timestamp { get; set; }
}

public class AuditEventPage
{
    public List<AuditEvent> Events { get; set; } = new();
    public int PageSize { get; set; }
    public string? NextCursor { get; set; }
    public bool HasMore => NextCursor is not null;
}

public sealed record AuditEventQuery(
    string? UserId = null,
    string? Action = null,
    string? ResourceType = null,
    string? ResourceId = null,
    DateTime? From = null,
    DateTime? To = null,
    string? Cursor = null,
    int PageSize = 20);

public class InvalidAuditQueryException : ArgumentException
{
    public InvalidAuditQueryException(string message) : base(message)
    {
    }
}
