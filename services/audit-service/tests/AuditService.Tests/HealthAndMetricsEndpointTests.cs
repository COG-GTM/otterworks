using System.Net;
using System.Text.Json;
using Amazon.DynamoDBv2;
using Amazon.DynamoDBv2.Model;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using Moq;

namespace AuditService.Tests;

public class HealthAndMetricsEndpointTests
{
    private readonly Mock<IAmazonDynamoDB> _mockDynamoDb;

    public HealthAndMetricsEndpointTests()
    {
        _mockDynamoDb = new Mock<IAmazonDynamoDB>();
    }

    [Fact]
    public async Task Health_WhenDynamoDbReachable_ShouldReturnHealthy()
    {
        _mockDynamoDb
            .Setup(d => d.ListTablesAsync(It.IsAny<CancellationToken>()))
            .ReturnsAsync(new ListTablesResponse { TableNames = new List<string> { "otterworks-audit-events" } });

        using var host = CreateHost();
        using var client = host.CreateClient();

        var response = await client.GetAsync("/health");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);

        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        Assert.Equal("healthy", document.RootElement.GetProperty("status").GetString());
        Assert.Equal("audit-service", document.RootElement.GetProperty("service").GetString());
    }

    [Fact]
    public async Task Health_WhenDynamoDbUnreachable_ShouldReturn503()
    {
        _mockDynamoDb
            .Setup(d => d.ListTablesAsync(It.IsAny<CancellationToken>()))
            .ThrowsAsync(new AmazonDynamoDBException("no route to host"));

        using var host = CreateHost();
        using var client = host.CreateClient();

        var response = await client.GetAsync("/health");

        Assert.Equal(HttpStatusCode.ServiceUnavailable, response.StatusCode);

        using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
        Assert.Equal("unhealthy", document.RootElement.GetProperty("status").GetString());
    }

    [Fact]
    public async Task Metrics_ShouldExposePrometheusTextExposition()
    {
        using var host = CreateHost();
        using var client = host.CreateClient();

        var response = await client.GetAsync("/metrics");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal("text/plain", response.Content.Headers.ContentType?.MediaType);

        var body = await response.Content.ReadAsStringAsync();
        Assert.Contains("# TYPE", body, StringComparison.Ordinal);
    }

    private AuditServiceTestHost CreateHost() => new(services =>
    {
        services.RemoveAll<IAmazonDynamoDB>();
        services.AddSingleton(_mockDynamoDb.Object);
    });
}
