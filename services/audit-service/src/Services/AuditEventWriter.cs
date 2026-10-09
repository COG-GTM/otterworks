using System.Text;
using System.Text.Json;

namespace OtterWorks.AuditService.Services;

// Serializes audit events incrementally to a stream so exports never hold the full payload in memory.
public abstract class AuditEventWriter : IDisposable
{
    public static AuditEventWriter Create(Stream stream, bool csv) =>
        csv ? new CsvAuditEventWriter(stream) : new JsonAuditEventWriter(stream);

    public abstract void Write(AuditEvent auditEvent);

    public abstract void Flush();

    public abstract void Finish();

    public abstract void Dispose();

    private sealed class JsonAuditEventWriter : AuditEventWriter
    {
        private static readonly JsonSerializerOptions SerializerOptions = new() { WriteIndented = true };
        private readonly Utf8JsonWriter _writer;

        public JsonAuditEventWriter(Stream stream)
        {
            _writer = new Utf8JsonWriter(stream, new JsonWriterOptions { Indented = true });
            _writer.WriteStartArray();
        }

        public override void Write(AuditEvent auditEvent) =>
            JsonSerializer.Serialize(_writer, auditEvent, SerializerOptions);

        public override void Flush() => _writer.Flush();

        public override void Finish()
        {
            _writer.WriteEndArray();
            _writer.Flush();
        }

        public override void Dispose() => _writer.Dispose();
    }

    private sealed class CsvAuditEventWriter : AuditEventWriter
    {
        private readonly StreamWriter _writer;

        public CsvAuditEventWriter(Stream stream)
        {
            _writer = new StreamWriter(stream, new UTF8Encoding(false), leaveOpen: true);
            _writer.WriteLine("Id,Timestamp,UserId,Action,ResourceType,ResourceId,IpAddress,UserAgent");
        }

        public override void Write(AuditEvent e) =>
            _writer.WriteLine($"\"{Esc(e.Id)}\",\"{e.Timestamp:O}\",\"{Esc(e.UserId)}\",\"{Esc(e.Action)}\",\"{Esc(e.ResourceType)}\",\"{Esc(e.ResourceId)}\",\"{Esc(e.IpAddress)}\",\"{Esc(e.UserAgent)}\"");

        public override void Flush() => _writer.Flush();

        public override void Finish() => _writer.Flush();

        public override void Dispose() => _writer.Dispose();

        private static string Esc(string? value) =>
            value?.Replace("\"", "\"\"") ?? string.Empty;
    }
}
