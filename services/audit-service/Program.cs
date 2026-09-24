using Amazon.DynamoDBv2;
using Amazon.S3;
using Amazon.SimpleNotificationService;
using Amazon.SQS;
using OpenTelemetry.Resources;
using OpenTelemetry.Trace;
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

// File-service lookup backing the resource-history access rule
var fileServiceUrl = builder.Configuration["FILE_SERVICE_URL"] ?? "http://file-service:8082";
builder.Services.AddHttpClient<IResourceAccessAuthorizer, FileResourceAccessAuthorizer>(client =>
{
    client.BaseAddress = new Uri(fileServiceUrl);
    client.Timeout = TimeSpan.FromSeconds(5);
});

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

// Middleware pipeline
app.UseMiddleware<ErrorHandlingMiddleware>();
app.UseMiddleware<RequestLoggingMiddleware>();

// Prometheus metrics endpoint
app.UseHttpMetrics();

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
