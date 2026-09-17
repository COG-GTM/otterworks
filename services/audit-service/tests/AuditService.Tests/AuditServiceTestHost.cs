using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using Microsoft.Extensions.Hosting;

namespace AuditService.Tests;

/// <summary>
/// Boots the real audit-service pipeline in-memory. The SQS background consumer is removed so
/// no test ever talks to AWS; callers replace the remaining boundary services with mocks.
/// </summary>
internal sealed class AuditServiceTestHost : IDisposable
{
    private readonly WebApplicationFactory<Program> _factory;

    public AuditServiceTestHost(Action<IServiceCollection> configureServices)
    {
        _factory = new WebApplicationFactory<Program>()
            .WithWebHostBuilder(builder => builder.ConfigureServices(services =>
            {
                services.RemoveAll<IHostedService>();
                configureServices(services);
            }));
    }

    public HttpClient CreateClient() => _factory.CreateClient();

    public void Dispose() => _factory.Dispose();
}
