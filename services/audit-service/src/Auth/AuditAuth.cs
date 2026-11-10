using System.Security.Claims;
using System.Security.Cryptography;
using System.Text;
using System.Text.Encodings.Web;
using Microsoft.AspNetCore.Authentication;
using Microsoft.Extensions.Options;
using Prometheus;

namespace OtterWorks.AuditService.Auth;

public static class AuditAuth
{
    public const string IngestScheme = "AuditIngestToken";
    public const string IngestPolicy = "AuditIngest";
    public const string AdminPolicy = "AuditAdmin";
    public const string IngestTokenHeader = "X-Audit-Token";
    public const string IngestTokensConfigKey = "AUDIT_INGEST_TOKENS";
    public const string JwtSecretConfigKey = "JWT_SECRET";
    public const string AdminRole = "ADMIN";

    public static IReadOnlyList<string> ParseTokens(string? raw) =>
        string.IsNullOrWhiteSpace(raw)
            ? Array.Empty<string>()
            : raw.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);

    public static bool IsAdmin(ClaimsPrincipal user)
    {
        if (user.Identity?.IsAuthenticated != true)
            return false;

        var tokenType = user.FindFirst("type")?.Value;
        if (tokenType is not null && !string.Equals(tokenType, "access", StringComparison.OrdinalIgnoreCase))
            return false;

        return user.FindAll("roles").Concat(user.FindAll("role")).Concat(user.FindAll(ClaimTypes.Role))
            .Any(c => string.Equals(c.Value, AdminRole, StringComparison.OrdinalIgnoreCase));
    }
}

public sealed class AuditIngestOptions
{
    public IReadOnlyList<string> Tokens { get; set; } = Array.Empty<string>();
}

/// <summary>
/// Authenticates service-to-service writes with a shared X-Audit-Token from the AUDIT_INGEST_TOKENS
/// allow-list. When the allow-list is empty, writes are accepted (open mode) so tenants deployed
/// without the secret keep working; Program logs a startup warning in that case.
/// </summary>
public sealed class AuditIngestTokenHandler : AuthenticationHandler<AuthenticationSchemeOptions>
{
    private static readonly Counter IngestRejected = Metrics.CreateCounter(
        "audit_ingest_rejected_total",
        "Audit event writes rejected because the X-Audit-Token header was missing or invalid.");

    private readonly AuditIngestOptions _ingestOptions;

    public AuditIngestTokenHandler(
        IOptionsMonitor<AuthenticationSchemeOptions> options,
        ILoggerFactory logger,
        UrlEncoder encoder,
        IOptions<AuditIngestOptions> ingestOptions)
        : base(options, logger, encoder)
    {
        _ingestOptions = ingestOptions.Value;
    }

    protected override Task<AuthenticateResult> HandleAuthenticateAsync()
    {
        if (_ingestOptions.Tokens.Count == 0)
            return Task.FromResult(Success("open"));

        var presented = Request.Headers[AuditAuth.IngestTokenHeader].ToString();
        if (string.IsNullOrEmpty(presented))
            return Task.FromResult(AuthenticateResult.NoResult());

        var presentedBytes = Encoding.UTF8.GetBytes(presented);
        var matched = _ingestOptions.Tokens.Any(t =>
            CryptographicOperations.FixedTimeEquals(presentedBytes, Encoding.UTF8.GetBytes(t)));

        return Task.FromResult(matched
            ? Success("token")
            : AuthenticateResult.Fail("Invalid audit ingest token."));
    }

    protected override async Task HandleChallengeAsync(AuthenticationProperties properties)
    {
        IngestRejected.Inc();
        Logger.LogWarning("Rejected audit ingest from {RemoteIp}: missing or invalid {Header}",
            Context.Connection.RemoteIpAddress, AuditAuth.IngestTokenHeader);
        Response.StatusCode = StatusCodes.Status401Unauthorized;
        await Response.WriteAsJsonAsync(new { error = $"Missing or invalid {AuditAuth.IngestTokenHeader} header." });
    }

    private AuthenticateResult Success(string mode)
    {
        var identity = new ClaimsIdentity(
            new[] { new Claim("ingest_mode", mode), new Claim(ClaimTypes.Role, "audit-ingest") },
            Scheme.Name);
        return AuthenticateResult.Success(new AuthenticationTicket(new ClaimsPrincipal(identity), Scheme.Name));
    }
}
