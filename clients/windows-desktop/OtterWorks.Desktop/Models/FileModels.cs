using System;
using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace OtterWorks.Desktop.Models
{
    /// <summary>A file as returned by the file service. Fields are snake_case.</summary>
    public class FileItem
    {
        [JsonPropertyName("id")]
        public string Id { get; set; }

        [JsonPropertyName("name")]
        public string Name { get; set; }

        [JsonPropertyName("size")]
        public long? Size { get; set; }

        [JsonPropertyName("content_type")]
        public string ContentType { get; set; }

        [JsonPropertyName("created_at")]
        public DateTimeOffset? CreatedAt { get; set; }
    }

    /// <summary>Paged response for GET /files.</summary>
    public class FileListResponse
    {
        [JsonPropertyName("files")]
        public List<FileItem> Files { get; set; } = new List<FileItem>();

        [JsonPropertyName("total")]
        public int Total { get; set; }

        [JsonPropertyName("page")]
        public int Page { get; set; }

        [JsonPropertyName("page_size")]
        public int PageSize { get; set; }
    }
}
