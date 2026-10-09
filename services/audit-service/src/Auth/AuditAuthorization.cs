using System.Security.Claims;
using System.Text;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.IdentityModel.Tokens;

namespace OtterWorks.AuditService.Auth;

public static class AuditAuthorization
{
    public const string AuthenticatedPolicy = "AuditAuthenticated";
    public const string AuditorPolicy = "AuditAuditor";
    public const string RolesClaim = "roles";

    private const string TokenTypeClaim = "type";
    private const string AccessTokenType = "access";
    private const int MinimumSecretBytes = 32;

    public static readonly string[] DefaultAuditorRoles = ["ADMIN", "OWNER"];

    public static IServiceCollection AddAuditAuthorization(this IServiceCollection services, IConfiguration configuration)
    {
        var secret = configuration["JWT_SECRET"];
        if (string.IsNullOrWhiteSpace(secret))
            throw new InvalidOperationException("JWT_SECRET must be configured for audit-service authentication.");

        var signingKey = Encoding.UTF8.GetBytes(secret);
        if (signingKey.Length < MinimumSecretBytes)
            throw new InvalidOperationException($"JWT_SECRET must be at least {MinimumSecretBytes} bytes.");

        var configuredRoles = configuration.GetSection("Audit:AuditorRoles").Get<string[]>();
        var auditorRoles = configuredRoles is { Length: > 0 } ? configuredRoles : DefaultAuditorRoles;

        services
            .AddAuthentication(JwtBearerDefaults.AuthenticationScheme)
            .AddJwtBearer(options =>
            {
                options.MapInboundClaims = false;
                options.TokenValidationParameters = new TokenValidationParameters
                {
                    ValidateIssuer = false,
                    ValidateAudience = false,
                    ValidateLifetime = true,
                    RequireExpirationTime = true,
                    ValidateIssuerSigningKey = true,
                    IssuerSigningKey = new SymmetricSecurityKey(signingKey),
                    ValidAlgorithms =
                    [
                        SecurityAlgorithms.HmacSha256,
                        SecurityAlgorithms.HmacSha384,
                        SecurityAlgorithms.HmacSha512,
                    ],
                    NameClaimType = "sub",
                    RoleClaimType = RolesClaim,
                    ClockSkew = TimeSpan.FromSeconds(30),
                };
            });

        services.AddAuthorization(options =>
        {
            options.AddPolicy(AuthenticatedPolicy, policy => policy
                .RequireAuthenticatedUser()
                .RequireClaim(TokenTypeClaim, AccessTokenType)
                .RequireAssertion(ctx => GetUserId(ctx.User) is not null));

            options.AddPolicy(AuditorPolicy, policy => policy
                .RequireAuthenticatedUser()
                .RequireClaim(TokenTypeClaim, AccessTokenType)
                .RequireAssertion(ctx => GetUserId(ctx.User) is not null)
                .RequireRole(auditorRoles));
        });

        return services;
    }

    public static string? GetUserId(ClaimsPrincipal user)
    {
        var userId = user.FindFirst("sub")?.Value;
        if (string.IsNullOrWhiteSpace(userId))
            userId = user.FindFirst("user_id")?.Value;
        return string.IsNullOrWhiteSpace(userId) ? null : userId;
    }
}
