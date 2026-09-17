using Amazon.DynamoDBv2;
using Amazon.DynamoDBv2.Model;
using Microsoft.Extensions.Diagnostics.HealthChecks;
using Moq;

namespace AuditService.Tests;

public class DynamoDbHealthCheckTests
{
    private readonly Mock<IAmazonDynamoDB> _mockDynamoDb;
    private readonly DynamoDbHealthCheck _healthCheck;

    public DynamoDbHealthCheckTests()
    {
        _mockDynamoDb = new Mock<IAmazonDynamoDB>();
        _healthCheck = new DynamoDbHealthCheck(_mockDynamoDb.Object);
    }

    [Fact]
    public async Task CheckHealthAsync_WhenListTablesSucceeds_ShouldReportHealthy()
    {
        _mockDynamoDb
            .Setup(d => d.ListTablesAsync(It.IsAny<CancellationToken>()))
            .ReturnsAsync(new ListTablesResponse());

        var result = await _healthCheck.CheckHealthAsync(new HealthCheckContext());

        Assert.Equal(HealthStatus.Healthy, result.Status);
        Assert.Equal("DynamoDB is reachable", result.Description);
        Assert.Null(result.Exception);
    }

    [Fact]
    public async Task CheckHealthAsync_WhenListTablesThrows_ShouldReportUnhealthyWithException()
    {
        var failure = new AmazonDynamoDBException("credentials expired");
        _mockDynamoDb
            .Setup(d => d.ListTablesAsync(It.IsAny<CancellationToken>()))
            .ThrowsAsync(failure);

        var result = await _healthCheck.CheckHealthAsync(new HealthCheckContext());

        Assert.Equal(HealthStatus.Unhealthy, result.Status);
        Assert.Equal("DynamoDB is unreachable", result.Description);
        Assert.Same(failure, result.Exception);
    }

    [Fact]
    public async Task CheckHealthAsync_ShouldForwardCancellationToken()
    {
        using var cts = new CancellationTokenSource();
        _mockDynamoDb
            .Setup(d => d.ListTablesAsync(cts.Token))
            .ReturnsAsync(new ListTablesResponse());

        var result = await _healthCheck.CheckHealthAsync(new HealthCheckContext(), cts.Token);

        Assert.Equal(HealthStatus.Healthy, result.Status);
        _mockDynamoDb.Verify(d => d.ListTablesAsync(cts.Token), Times.Once);
    }
}
