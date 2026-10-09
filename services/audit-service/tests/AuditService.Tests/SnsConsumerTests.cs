using OtterWorks.AuditService.Services;
using Xunit;

namespace AuditService.Tests;

public class SnsConsumerTests
{
    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("  ")]
    public void QueueNameFor_WithoutTenant_UsesSharedLocalQueue(string? tenantId)
    {
        Assert.Equal("otterworks-audit-events-queue", SnsConsumer.QueueNameFor(tenantId));
    }

    [Fact]
    public void QueueNameFor_WithTenant_UsesPerTenantQueue()
    {
        Assert.Equal("otterworks-audit-events-queue-otterworks-t1", SnsConsumer.QueueNameFor("otterworks-t1"));
        Assert.NotEqual(SnsConsumer.QueueNameFor("tenant-a"), SnsConsumer.QueueNameFor("tenant-b"));
    }

    [Fact]
    public void QueueNameFor_SanitizesAndBoundsLength()
    {
        var name = SnsConsumer.QueueNameFor("a.b/c " + new string('x', 200));
        Assert.StartsWith("otterworks-audit-events-queue-a-b-c-", name);
        Assert.True(name.Length <= 80);
        Assert.Matches("^[A-Za-z0-9_-]+$", name);
    }
}
