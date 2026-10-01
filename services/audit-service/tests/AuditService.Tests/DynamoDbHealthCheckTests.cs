using Amazon.DynamoDBv2;
using Amazon.DynamoDBv2.Model;
using Microsoft.Extensions.Diagnostics.HealthChecks;
using Moq;

namespace AuditService.Tests;

public class DynamoDbHealthCheckTests
{
    private readonly Mock<IAmazonDynamoDB> _mockDynamoDb = new();

    [Fact]
    public async Task CheckHealthAsync_ShouldReportHealthy_WhenTablesCanBeListed()
    {
        _mockDynamoDb
            .Setup(d => d.ListTablesAsync(It.IsAny<CancellationToken>()))
            .ReturnsAsync(new ListTablesResponse { TableNames = new List<string> { "otterworks-audit-events" } });

        var result = await new DynamoDbHealthCheck(_mockDynamoDb.Object)
            .CheckHealthAsync(new HealthCheckContext());

        Assert.Equal(HealthStatus.Healthy, result.Status);
        Assert.Equal("DynamoDB is reachable", result.Description);
    }

    [Fact]
    public async Task CheckHealthAsync_ShouldReportUnhealthy_WhenListTablesThrows()
    {
        var failure = new AmazonDynamoDBException("connection refused");
        _mockDynamoDb
            .Setup(d => d.ListTablesAsync(It.IsAny<CancellationToken>()))
            .ThrowsAsync(failure);

        var result = await new DynamoDbHealthCheck(_mockDynamoDb.Object)
            .CheckHealthAsync(new HealthCheckContext());

        Assert.Equal(HealthStatus.Unhealthy, result.Status);
        Assert.Equal("DynamoDB is unreachable", result.Description);
        Assert.Same(failure, result.Exception);
    }
}
