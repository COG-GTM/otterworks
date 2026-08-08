using System.Net;
using System.Text.Json;
using Amazon.DynamoDBv2;
using Amazon.DynamoDBv2.Model;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using Microsoft.Extensions.Diagnostics.HealthChecks;
using Microsoft.Extensions.Hosting;
using Moq;
using IAuditService = OtterWorks.AuditService.Services.IAuditService;

namespace AuditService.Tests;

[Collection(AuditApiCollection.Name)]
public class ProgramEndpointsTests
{
    private readonly Mock<IAmazonDynamoDB> _mockDynamoDb = new();

    [Fact]
    public async Task Health_ShouldReturnHealthy_WhenDynamoDbIsReachable()
    {
        _mockDynamoDb
            .Setup(d => d.ListTablesAsync(It.IsAny<CancellationToken>()))
            .ReturnsAsync(new ListTablesResponse());

        await using var factory = CreateFactory();
        using var client = factory.CreateClient();

        var response = await client.GetAsync("/health");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        Assert.Equal("healthy", document.RootElement.GetProperty("status").GetString());
        Assert.Equal("audit-service", document.RootElement.GetProperty("service").GetString());
    }

    [Fact]
    public async Task Health_ShouldReturn503_WhenDynamoDbIsUnreachable()
    {
        _mockDynamoDb
            .Setup(d => d.ListTablesAsync(It.IsAny<CancellationToken>()))
            .ThrowsAsync(new AmazonDynamoDBException("unreachable"));

        await using var factory = CreateFactory();
        using var client = factory.CreateClient();

        var response = await client.GetAsync("/health");

        Assert.Equal(HttpStatusCode.ServiceUnavailable, response.StatusCode);
        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        Assert.Equal("unhealthy", document.RootElement.GetProperty("status").GetString());
    }

    [Fact]
    public async Task Metrics_ShouldReturnPrometheusText()
    {
        await using var factory = CreateFactory();
        using var client = factory.CreateClient();

        var response = await client.GetAsync("/metrics");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal("text/plain", response.Content.Headers.ContentType?.MediaType);
    }

    [Fact]
    public async Task DynamoDbHealthCheck_ShouldReportHealthy_WhenListTablesSucceeds()
    {
        _mockDynamoDb
            .Setup(d => d.ListTablesAsync(It.IsAny<CancellationToken>()))
            .ReturnsAsync(new ListTablesResponse());

        var healthCheck = new DynamoDbHealthCheck(_mockDynamoDb.Object);

        var result = await healthCheck.CheckHealthAsync(new HealthCheckContext());

        Assert.Equal(HealthStatus.Healthy, result.Status);
        Assert.Equal("DynamoDB is reachable", result.Description);
    }

    [Fact]
    public async Task DynamoDbHealthCheck_ShouldReportUnhealthy_WhenListTablesThrows()
    {
        var failure = new AmazonDynamoDBException("unreachable");
        _mockDynamoDb
            .Setup(d => d.ListTablesAsync(It.IsAny<CancellationToken>()))
            .ThrowsAsync(failure);

        var healthCheck = new DynamoDbHealthCheck(_mockDynamoDb.Object);

        var result = await healthCheck.CheckHealthAsync(new HealthCheckContext());

        Assert.Equal(HealthStatus.Unhealthy, result.Status);
        Assert.Equal("DynamoDB is unreachable", result.Description);
        Assert.Same(failure, result.Exception);
    }

    private WebApplicationFactory<Program> CreateFactory() =>
        new WebApplicationFactory<Program>().WithWebHostBuilder(builder =>
            builder.ConfigureServices(services =>
            {
                // Drops the SnsConsumer background loop so nothing talks to SQS.
                services.RemoveAll<IHostedService>();
                services.RemoveAll<IAuditService>();
                services.RemoveAll<IAmazonDynamoDB>();
                services.AddSingleton(_mockDynamoDb.Object);
                services.AddSingleton(Mock.Of<IAuditService>());
            }));
}
