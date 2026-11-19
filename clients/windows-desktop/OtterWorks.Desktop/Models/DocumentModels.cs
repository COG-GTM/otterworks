using System;
using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace OtterWorks.Desktop.Models
{
    /// <summary>Request body for POST /documents.</summary>
    public class CreateDocumentRequest
    {
        [JsonPropertyName("title")]
        public string Title { get; set; }
    }

    /// <summary>
    /// A document as returned by the document service. Fields are snake_case.
    /// </summary>
    public class Document
    {
        [JsonPropertyName("id")]
        public string Id { get; set; }

        [JsonPropertyName("title")]
        public string Title { get; set; }

        [JsonPropertyName("content")]
        public string Content { get; set; }

        [JsonPropertyName("content_type")]
        public string ContentType { get; set; }

        [JsonPropertyName("owner_id")]
        public string OwnerId { get; set; }

        [JsonPropertyName("folder_id")]
        public string FolderId { get; set; }

        [JsonPropertyName("is_deleted")]
        public bool IsDeleted { get; set; }

        [JsonPropertyName("word_count")]
        public int WordCount { get; set; }

        [JsonPropertyName("version")]
        public int Version { get; set; }

        [JsonPropertyName("created_at")]
        public DateTimeOffset? CreatedAt { get; set; }

        [JsonPropertyName("updated_at")]
        public DateTimeOffset? UpdatedAt { get; set; }
    }

    /// <summary>Paged response for GET /documents.</summary>
    public class DocumentListResponse
    {
        [JsonPropertyName("items")]
        public List<Document> Items { get; set; } = new List<Document>();

        [JsonPropertyName("total")]
        public int Total { get; set; }

        [JsonPropertyName("page")]
        public int Page { get; set; }

        [JsonPropertyName("size")]
        public int Size { get; set; }

        [JsonPropertyName("pages")]
        public int Pages { get; set; }
    }
}
