using System.Security.Claims;
using System.Security.Cryptography;
using System.Text;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.IdentityModel.Tokens;

namespace OtterWorks.AuditService.Auth;

/// <summary>
/// Validates the access tokens issued by auth-service (HMAC, shared JWT_SECRET, type=access)
/// so the audit API never relies on the gateway having checked the caller.
/// </summary>
public static class AuditAuthentication
{
    public const string CallerPolicy = "AuditCaller";
    public const string AdminPolicy = "AuditAdmin";

    // auth-service roles are USER/EDITOR/ADMIN/OWNER; admin-service also issues super_admin.
    private static readonly string[] AdminRoles = { "ADMIN", "OWNER", "SUPER_ADMIN" };

    private const int MinSecretBytes = 32;

    public static IServiceCollection AddAuditAuthentication(this IServiceCollection services, IConfiguration configuration)
    {
        var signingKey = BuildSigningKey(configuration["JWT_SECRET"]);

        services
            .AddAuthentication(JwtBearerDefaults.AuthenticationScheme)
            .AddJwtBearer(options =>
            {
                options.MapInboundClaims = false;
                options.TokenValidationParameters = new TokenValidationParameters
                {
                    ValidateIssuerSigningKey = true,
                    IssuerSigningKey = signingKey,
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
                        if (principal?.FindFirst("type")?.Value != "access")
                        {
                            context.Fail("Only access tokens are accepted.");
                        }
                        else if (string.IsNullOrWhiteSpace(principal.FindFirst("sub")?.Value))
                        {
                            context.Fail("Token has no subject.");
                        }

                        return Task.CompletedTask;
                    },
                };
            });

        services.AddAuthorization(options =>
        {
            options.AddPolicy(CallerPolicy, policy => policy.RequireAuthenticatedUser());
            options.AddPolicy(AdminPolicy, policy => policy
                .RequireAuthenticatedUser()
                .RequireAssertion(context => IsAdmin(context.User)));
        });

        return services;
    }

    public static string UserId(this ClaimsPrincipal user) =>
        user.FindFirst("sub")?.Value ?? string.Empty;

    public static bool IsAdmin(this ClaimsPrincipal user) =>
        user.FindAll("roles").Any(role => AdminRoles.Contains(role.Value, StringComparer.OrdinalIgnoreCase));

    public static bool HasUsableSecret(IConfiguration configuration)
    {
        var secret = configuration["JWT_SECRET"];
        return !string.IsNullOrEmpty(secret) && Encoding.UTF8.GetByteCount(secret) >= MinSecretBytes;
    }

    private static SymmetricSecurityKey BuildSigningKey(string? secret)
    {
        if (!string.IsNullOrEmpty(secret) && Encoding.UTF8.GetByteCount(secret) >= MinSecretBytes)
        {
            return new SymmetricSecurityKey(Encoding.UTF8.GetBytes(secret));
        }

        // Fail closed: with no usable shared secret no token can validate, so every
        // audit route answers 401 instead of falling back to an unauthenticated API.
        return new SymmetricSecurityKey(RandomNumberGenerator.GetBytes(64));
    }
}
