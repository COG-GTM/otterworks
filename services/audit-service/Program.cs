using Amazon.DynamoDBv2;
using Amazon.S3;
using Amazon.SimpleNotificationService;
using Amazon.SQS;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.Authorization;
using Microsoft.IdentityModel.Tokens;
using OpenTelemetry.Resources;
using OpenTelemetry.Trace;
using OtterWorks.AuditService.Auth;
using OtterWorks.AuditService.Config;
using OtterWorks.AuditService.Controllers;
using OtterWorks.AuditService.Middleware;
using OtterWorks.AuditService.Services;
using Prometheus;
using Serilog;
using Serilog.Formatting.Compact;
using IAuditService = OtterWorks.AuditService.Services.IAuditService;

var builder = WebApplication.CreateBuilder(args);

// Structured logging with Serilog
Log.Logger = new LoggerConfiguration()
    .ReadFrom.Configuration(builder.Configuration)
    .Enrich.WithProperty("service", "audit-service")
    .Enrich.FromLogContext()
    .WriteTo.Console(new CompactJsonFormatter())
    .CreateLogger();
builder.Host.UseSerilog();

// Configuration
var awsSection = builder.Configuration.GetSection("Aws");
builder.Services.Configure<AwsSettings>(awsSection);
var awsSettings = awsSection.Get<AwsSettings>() ?? new AwsSettings();

// AWS SDK clients
builder.Services.AddSingleton<IAmazonDynamoDB>(_ =>
{
    var config = new AmazonDynamoDBConfig { RegionEndpoint = Amazon.RegionEndpoint.GetBySystemName(awsSettings.Region) };
    if (!string.IsNullOrEmpty(awsSettings.EndpointUrl))
        config.ServiceURL = awsSettings.EndpointUrl;
    return new AmazonDynamoDBClient(config);
});

builder.Services.AddSingleton<IAmazonS3>(_ =>
{
    var config = new AmazonS3Config { RegionEndpoint = Amazon.RegionEndpoint.GetBySystemName(awsSettings.Region) };
    if (!string.IsNullOrEmpty(awsSettings.EndpointUrl))
    {
        config.ServiceURL = awsSettings.EndpointUrl;
        config.ForcePathStyle = true;
    }
    return new AmazonS3Client(config);
});

builder.Services.AddSingleton<IAmazonSQS>(_ =>
{
    var config = new AmazonSQSConfig { RegionEndpoint = Amazon.RegionEndpoint.GetBySystemName(awsSettings.Region) };
    if (!string.IsNullOrEmpty(awsSettings.EndpointUrl))
        config.ServiceURL = awsSettings.EndpointUrl;
    return new AmazonSQSClient(config);
});

builder.Services.AddSingleton<IAmazonSimpleNotificationService>(_ =>
{
    var config = new AmazonSimpleNotificationServiceConfig { RegionEndpoint = Amazon.RegionEndpoint.GetBySystemName(awsSettings.Region) };
    if (!string.IsNullOrEmpty(awsSettings.EndpointUrl))
        config.ServiceURL = awsSettings.EndpointUrl;
    return new AmazonSimpleNotificationServiceClient(config);
});

// Services (Clean Architecture: Controllers -> Services -> Repositories)
builder.Services.AddSingleton<IAuditRepository, DynamoDbAuditRepository>();
builder.Services.AddSingleton<IAuditArchiver, S3AuditArchiver>();
builder.Services.AddSingleton<IAuditService, OtterWorks.AuditService.Services.AuditService>();

// Self-auditing of audit-service's own sensitive operations
builder.Services.Configure<SelfAuditOptions>(_ => { });
builder.Services.AddSingleton<SelfAuditor>();

// AuthN/Z: X-Audit-Token for service ingest, admin JWTs (auth-service HMAC, JWT_SECRET) for reads.
builder.Services.AddOptions<AuditIngestOptions>()
    .Configure<IConfiguration>((options, config) =>
        options.Tokens = AuditAuth.ParseTokens(config[AuditAuth.IngestTokensConfigKey]));

builder.Services.AddAuthentication()
    .AddScheme<AuthenticationSchemeOptions, AuditIngestTokenHandler>(AuditAuth.IngestScheme, _ => { })
    .AddJwtBearer();

builder.Services.AddOptions<JwtBearerOptions>(JwtBearerDefaults.AuthenticationScheme)
    .Configure<IConfiguration>((options, config) =>
    {
        var secret = config[AuditAuth.JwtSecretConfigKey];
        options.MapInboundClaims = false;
        options.TokenValidationParameters = new TokenValidationParameters
        {
            ValidateIssuer = false,
            ValidateAudience = false,
            ValidateLifetime = true,
            ValidateIssuerSigningKey = true,
            RequireSignedTokens = true,
            ValidAlgorithms = new[] { SecurityAlgorithms.HmacSha256, SecurityAlgorithms.HmacSha384, SecurityAlgorithms.HmacSha512 },
            IssuerSigningKey = string.IsNullOrEmpty(secret)
                ? null
                : new SymmetricSecurityKey(System.Text.Encoding.UTF8.GetBytes(secret)),
            NameClaimType = "sub",
            RoleClaimType = "roles",
        };
    });

builder.Services.AddAuthorization(options =>
{
    options.AddPolicy(AuditAuth.IngestPolicy, policy => policy
        .AddAuthenticationSchemes(AuditAuth.IngestScheme)
        .RequireAuthenticatedUser());
    options.AddPolicy(AuditAuth.AdminPolicy, policy => policy
        .AddAuthenticationSchemes(JwtBearerDefaults.AuthenticationScheme)
        .RequireAuthenticatedUser()
        .RequireAssertion(ctx => AuditAuth.IsAdmin(ctx.User)));
});
builder.Services.AddSingleton<IAuthorizationMiddlewareResultHandler, DeniedAuditResultHandler>();

// SNS/SQS Consumer background service
builder.Services.AddHostedService<SnsConsumer>();

// OpenTelemetry tracing
builder.Services.AddOpenTelemetry()
    .WithTracing(tracing =>
    {
        tracing
            .SetResourceBuilder(ResourceBuilder.CreateDefault().AddService("audit-service"))
            .AddAspNetCoreInstrumentation()
            .AddOtlpExporter();
    });

// Health checks with DynamoDB connectivity check
builder.Services.AddHealthChecks()
    .AddCheck<DynamoDbHealthCheck>("dynamodb");

// Prometheus metrics
builder.Services.AddSingleton(Metrics.DefaultRegistry);

var app = builder.Build();

if (AuditAuth.ParseTokens(app.Configuration[AuditAuth.IngestTokensConfigKey]).Count == 0)
{
    Log.Warning("{Key} is not set: POST /api/v1/audit/events accepts unauthenticated writes. Set it to a comma-separated list of service ingest tokens.",
        AuditAuth.IngestTokensConfigKey);
}

if (string.IsNullOrEmpty(app.Configuration[AuditAuth.JwtSecretConfigKey]))
{
    Log.Warning("{Key} is not set: admin read, export and archive endpoints will reject every request.",
        AuditAuth.JwtSecretConfigKey);
}

// Middleware pipeline
app.UseMiddleware<ErrorHandlingMiddleware>();
app.UseMiddleware<RequestLoggingMiddleware>();

// Prometheus metrics endpoint
app.UseHttpMetrics();

app.UseAuthentication();
app.UseAuthorization();

// Health check
app.MapGet("/health", async (IAmazonDynamoDB dynamoDb) =>
{
    try
    {
        await dynamoDb.ListTablesAsync();
        return Results.Ok(new { status = "healthy", service = "audit-service", timestamp = DateTime.UtcNow });
    }
    catch (Exception ex)
    {
        Log.Warning(ex, "DynamoDB health check failed");
        return Results.Json(
            new { status = "unhealthy", service = "audit-service", timestamp = DateTime.UtcNow },
            statusCode: 503);
    }
});

// Prometheus metrics
app.MapGet("/metrics", async () =>
{
    using var stream = new MemoryStream();
    await Metrics.DefaultRegistry.CollectAndExportAsTextAsync(stream);
    stream.Position = 0;
    using var reader = new StreamReader(stream);
    var metricsText = await reader.ReadToEndAsync();
    return Results.Text(metricsText, "text/plain; version=0.0.4; charset=utf-8");
});

// Map audit API endpoints via controller
app.MapAuditEndpoints();

app.Run();

public partial class Program
{
}

// Health check implementation
public class DynamoDbHealthCheck : Microsoft.Extensions.Diagnostics.HealthChecks.IHealthCheck
{
    private readonly IAmazonDynamoDB _dynamoDb;

    public DynamoDbHealthCheck(IAmazonDynamoDB dynamoDb)
    {
        _dynamoDb = dynamoDb;
    }

    public async Task<Microsoft.Extensions.Diagnostics.HealthChecks.HealthCheckResult> CheckHealthAsync(
        Microsoft.Extensions.Diagnostics.HealthChecks.HealthCheckContext context,
        CancellationToken cancellationToken = default)
    {
        try
        {
            await _dynamoDb.ListTablesAsync(cancellationToken);
            return Microsoft.Extensions.Diagnostics.HealthChecks.HealthCheckResult.Healthy("DynamoDB is reachable");
        }
        catch (Exception ex)
        {
            return Microsoft.Extensions.Diagnostics.HealthChecks.HealthCheckResult.Unhealthy("DynamoDB is unreachable", ex);
        }
    }
}

// Make Program class accessible for test projects
public partial class Program { }
