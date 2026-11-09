using System.Security.Claims;
using System.Security.Cryptography;
using System.Text;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.Extensions.Options;
using Microsoft.IdentityModel.Tokens;

namespace OtterWorks.AuditService.Auth;

/// <summary>
/// Verifies the access tokens issued by auth-service (forwarded unchanged by the
/// api-gateway) and exposes the caller's identity and admin status.
/// </summary>
public static class AuditAuthentication
{
    public const string AdminPolicy = "AuditAdmin";

    private static readonly string[] AdminRoles = { "admin", "owner", "super_admin" };

    public static IServiceCollection AddAuditAuthentication(this IServiceCollection services)
    {
        services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme)
            .AddJwtBearer();

        services.AddOptions<JwtBearerOptions>(JwtBearerDefaults.AuthenticationScheme)
            .Configure<IConfiguration, ILoggerFactory>((options, configuration, loggerFactory) =>
            {
                var secret = configuration["JWT_SECRET"];
                byte[] keyBytes;
                if (string.IsNullOrEmpty(secret))
                {
                    // Fail closed: with no shared secret configured no token can validate.
                    loggerFactory.CreateLogger(typeof(AuditAuthentication))
                        .LogError("JWT_SECRET is not set; every audit API request will be rejected with 401");
                    keyBytes = RandomNumberGenerator.GetBytes(64);
                }
                else
                {
                    keyBytes = Encoding.UTF8.GetBytes(secret);
                }

                options.MapInboundClaims = false;
                options.TokenValidationParameters = new TokenValidationParameters
                {
                    IssuerSigningKey = new SymmetricSecurityKey(keyBytes),
                    ValidateIssuerSigningKey = true,
                    ValidAlgorithms = new[]
                    {
                        SecurityAlgorithms.HmacSha256,
                        SecurityAlgorithms.HmacSha384,
                        SecurityAlgorithms.HmacSha512,
                    },
                    ValidateIssuer = false,
                    ValidateAudience = false,
                    ValidateLifetime = true,
                    RequireExpirationTime = true,
                    ClockSkew = TimeSpan.FromSeconds(30),
                    NameClaimType = "sub",
                    RoleClaimType = "roles",
                };
                options.Events = new JwtBearerEvents
                {
                    OnTokenValidated = context =>
                    {
                        var principal = context.Principal;
                        var tokenType = principal?.FindFirstValue("type");
                        if (tokenType is not null && !string.Equals(tokenType, "access", StringComparison.OrdinalIgnoreCase))
                        {
                            context.Fail("Only access tokens are accepted.");
                        }
                        else if (string.IsNullOrEmpty(principal?.GetUserId()))
                        {
                            context.Fail("Token has no subject.");
                        }
                        return Task.CompletedTask;
                    },
                };
            });

        services.AddAuthorization(options =>
        {
            options.AddPolicy(AdminPolicy, policy => policy
                .RequireAuthenticatedUser()
                .RequireAssertion(ctx => ctx.User.IsAuditAdmin()));
        });

        return services;
    }

    public static string? GetUserId(this ClaimsPrincipal principal)
    {
        var userId = principal.FindFirstValue("sub");
        return string.IsNullOrEmpty(userId) ? principal.FindFirstValue("user_id") : userId;
    }

    public static bool IsAuditAdmin(this ClaimsPrincipal principal)
    {
        return principal.Claims
            .Where(c => c.Type is "roles" or "role")
            .Any(c => AdminRoles.Contains(c.Value, StringComparer.OrdinalIgnoreCase));
    }
}
