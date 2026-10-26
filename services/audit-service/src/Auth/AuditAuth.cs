using System.Security.Claims;
using System.Security.Cryptography;
using System.Text;
using System.Text.Encodings.Web;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.Extensions.Options;
using Microsoft.IdentityModel.Tokens;

namespace OtterWorks.AuditService.Auth;

/// <summary>
/// Authentication and authorization for the audit API.
///
/// Callers authenticate with either:
/// * an auth-service access token (<c>Authorization: Bearer</c>), validated against the
///   shared <c>JWT_SECRET</c>; or
/// * the internal service credential (<c>X-Service-Token</c>), compared to
///   <c>AUDIT_SERVICE_TOKEN</c>, for trusted callers such as report-service.
///
/// Admins (ADMIN/OWNER/SUPER_ADMIN roles) and service callers may read the whole trail;
/// everyone else is scoped to their own user id.
/// </summary>
public static class AuditAuth
{
    public const string ServiceTokenScheme = "ServiceToken";
    public const string ServiceTokenHeader = "X-Service-Token";
    public const string AdminPolicy = "AuditAdmin";
    public const string ServiceRole = "service";

    private const string SubjectClaim = "sub";
    private const string RolesClaim = "roles";
    private const string TokenTypeClaim = "type";

    private static readonly string[] AdminRoles = { "ADMIN", "OWNER", "SUPER_ADMIN" };

    public static IServiceCollection AddAuditAuth(this IServiceCollection services)
    {
        services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme)
            .AddJwtBearer(options =>
            {
                options.MapInboundClaims = false;
                options.TokenValidationParameters = new TokenValidationParameters
                {
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
                    NameClaimType = SubjectClaim,
                    RoleClaimType = RolesClaim,
                };
                options.Events = new JwtBearerEvents
                {
                    OnTokenValidated = context =>
                    {
                        var principal = context.Principal;
                        if (principal?.FindFirst(TokenTypeClaim)?.Value != "access" ||
                            string.IsNullOrWhiteSpace(principal.FindFirst(SubjectClaim)?.Value))
                        {
                            context.Fail("Access token required.");
                        }
                        return Task.CompletedTask;
                    },
                };
            })
            .AddScheme<ServiceTokenOptions, ServiceTokenHandler>(ServiceTokenScheme, _ => { });

        // Secrets are read from the final app configuration when the options are first built.
        services.AddOptions<JwtBearerOptions>(JwtBearerDefaults.AuthenticationScheme)
            .Configure<IConfiguration>((options, configuration) =>
            {
                var jwtSecret = configuration["JWT_SECRET"];
                // Without a configured secret, no bearer token can validate (fail closed).
                options.TokenValidationParameters.IssuerSigningKey = new SymmetricSecurityKey(
                    string.IsNullOrWhiteSpace(jwtSecret) ? RandomNumberGenerator.GetBytes(64) : Encoding.UTF8.GetBytes(jwtSecret));
            });
        services.AddOptions<ServiceTokenOptions>(ServiceTokenScheme)
            .Configure<IConfiguration>((options, configuration) => options.Token = configuration["AUDIT_SERVICE_TOKEN"]);

        services.AddAuthorization(options =>
        {
            var schemes = new[] { JwtBearerDefaults.AuthenticationScheme, ServiceTokenScheme };
            options.DefaultPolicy = new Microsoft.AspNetCore.Authorization.AuthorizationPolicyBuilder(schemes)
                .RequireAuthenticatedUser()
                .Build();
            options.AddPolicy(AdminPolicy, policy => policy
                .AddAuthenticationSchemes(schemes)
                .RequireAuthenticatedUser()
                .RequireAssertion(ctx => IsAdmin(ctx.User)));
        });

        return services;
    }

    public static bool IsAdmin(ClaimsPrincipal user) =>
        user.Identities.Any(i => i.IsAuthenticated && i.AuthenticationType == ServiceTokenScheme) ||
        user.FindAll(RolesClaim).Any(c => AdminRoles.Contains(c.Value, StringComparer.OrdinalIgnoreCase));

    public static string? GetUserId(ClaimsPrincipal user) => user.FindFirst(SubjectClaim)?.Value;

    public static bool CanAccessUser(ClaimsPrincipal user, string? userId) =>
        IsAdmin(user) || (!string.IsNullOrEmpty(userId) && string.Equals(GetUserId(user), userId, StringComparison.Ordinal));

    public sealed class ServiceTokenOptions : AuthenticationSchemeOptions
    {
        public string? Token { get; set; }
    }

    public sealed class ServiceTokenHandler : AuthenticationHandler<ServiceTokenOptions>
    {
        public ServiceTokenHandler(
            IOptionsMonitor<ServiceTokenOptions> options,
            ILoggerFactory logger,
            UrlEncoder encoder)
            : base(options, logger, encoder)
        {
        }

        protected override Task<AuthenticateResult> HandleAuthenticateAsync()
        {
            if (!Request.Headers.TryGetValue(ServiceTokenHeader, out var provided) || string.IsNullOrEmpty(provided))
                return Task.FromResult(AuthenticateResult.NoResult());

            var expected = Options.Token;
            if (string.IsNullOrEmpty(expected) ||
                !CryptographicOperations.FixedTimeEquals(
                    Encoding.UTF8.GetBytes(provided.ToString()),
                    Encoding.UTF8.GetBytes(expected)))
            {
                return Task.FromResult(AuthenticateResult.Fail("Invalid service token."));
            }

            var identity = new ClaimsIdentity(
                new[] { new Claim(SubjectClaim, ServiceRole), new Claim(RolesClaim, ServiceRole) },
                ServiceTokenScheme,
                SubjectClaim,
                RolesClaim);
            return Task.FromResult(AuthenticateResult.Success(
                new AuthenticationTicket(new ClaimsPrincipal(identity), ServiceTokenScheme)));
        }
    }
}
