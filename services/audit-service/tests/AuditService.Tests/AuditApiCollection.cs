namespace AuditService.Tests;

/// <summary>
/// Serialises the tests that boot the real host: prometheus-net's default registry and the
/// Serilog static logger are process-wide, so two hosts must not start at the same time.
/// </summary>
[CollectionDefinition(Name)]
public class AuditApiCollection
{
    public const string Name = "audit-api";
}
