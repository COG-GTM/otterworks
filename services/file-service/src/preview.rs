//! MIME resolution for uploads and inline (preview) delivery of stored files.

const GENERIC_MIME_TYPES: &[&str] = &[
    "",
    "application/octet-stream",
    "binary/octet-stream",
    "application/unknown",
];

/// Best-effort MIME type for a file extension (lowercase, without the dot).
fn mime_for_extension(ext: &str) -> Option<&'static str> {
    let mime = match ext {
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "gif" => "image/gif",
        "webp" => "image/webp",
        "bmp" => "image/bmp",
        "svg" => "image/svg+xml",
        "ico" => "image/x-icon",
        "avif" => "image/avif",
        "pdf" => "application/pdf",
        "mp4" | "m4v" => "video/mp4",
        "webm" => "video/webm",
        "mov" => "video/quicktime",
        "ogv" => "video/ogg",
        "mp3" => "audio/mpeg",
        "wav" => "audio/wav",
        "ogg" | "oga" => "audio/ogg",
        "m4a" => "audio/mp4",
        "flac" => "audio/flac",
        "aac" => "audio/aac",
        "txt" | "log" => "text/plain",
        "md" | "markdown" => "text/markdown",
        "csv" => "text/csv",
        "tsv" => "text/tab-separated-values",
        "html" | "htm" => "text/html",
        "css" => "text/css",
        "json" => "application/json",
        "xml" => "application/xml",
        "yaml" | "yml" => "application/x-yaml",
        "js" | "mjs" | "cjs" | "jsx" => "application/javascript",
        "ts" | "tsx" => "application/typescript",
        "sh" | "bash" => "application/x-sh",
        "py" | "rb" | "go" | "rs" | "java" | "kt" | "c" | "h" | "cpp" | "hpp" | "cs" | "php"
        | "swift" | "scala" | "sql" | "toml" | "ini" | "cfg" | "conf" | "env" | "properties"
        | "gradle" | "dockerfile" | "makefile" => "text/plain",
        "zip" => "application/zip",
        "docx" => "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xlsx" => "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "pptx" => "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        _ => return None,
    };
    Some(mime)
}

fn extension(file_name: &str) -> Option<String> {
    let base = file_name.rsplit('/').next().unwrap_or(file_name);
    match base.rsplit_once('.') {
        Some((_, ext)) if !ext.is_empty() => Some(ext.to_ascii_lowercase()),
        // Extensionless well-known names, e.g. "Dockerfile", "Makefile".
        _ => Some(base.to_ascii_lowercase()),
    }
}

/// Bytes of the object needed by [`looks_like_mpeg_ts`].
pub const SNIFF_LEN: usize = 189;

/// MPEG transport streams are whole 188-byte packets that each start with 0x47,
/// so anything shorter than one packet is never a stream.
pub fn looks_like_mpeg_ts(prefix: &[u8]) -> bool {
    prefix.len() >= 188 && prefix[0] == 0x47 && prefix.get(188).is_none_or(|b| *b == 0x47)
}

/// Browsers report TypeScript source (`.ts`) as `video/mp2t`, the same type as
/// a real MPEG transport stream; only the content can tell them apart.
pub fn is_ambiguous_ts(content_type: &str, file_name: &str) -> bool {
    content_type.trim().eq_ignore_ascii_case("video/mp2t")
        && matches!(
            extension(file_name).as_deref(),
            Some("ts" | "tsx" | "mts" | "cts")
        )
}

/// Keep the client-supplied MIME type unless it is missing/generic, in which
/// case infer it from the file name. `content_prefix` (the first
/// [`SNIFF_LEN`] bytes) disambiguates `.ts` source from MPEG-TS video.
pub fn resolve_mime_type(
    content_type: &str,
    file_name: &str,
    content_prefix: Option<&[u8]>,
) -> String {
    let declared = content_type.trim().to_ascii_lowercase();
    let ext = extension(file_name);
    let mislabeled_source =
        is_ambiguous_ts(content_type, file_name) && !content_prefix.is_some_and(looks_like_mpeg_ts);
    if !GENERIC_MIME_TYPES.contains(&declared.as_str()) && !mislabeled_source {
        return content_type.trim().to_string();
    }
    ext.and_then(|ext| mime_for_extension(&ext))
        .unwrap_or("application/octet-stream")
        .to_string()
}

/// Content-Type to serve when a file is previewed inline. Media types the
/// browser renders natively pass through; markup and other text-like types
/// are downgraded to `text/plain` so the object can never execute as a page.
pub fn inline_content_type(
    mime_type: &str,
    file_name: &str,
    content_prefix: Option<&[u8]>,
) -> String {
    let mime = resolve_mime_type(mime_type, file_name, content_prefix).to_ascii_lowercase();
    let essence = mime.split(';').next().unwrap_or("").trim();

    // SVG can carry script, so it is served as text like other markup.
    let renders_natively = essence == "application/pdf"
        || ((essence.starts_with("image/")
            || essence.starts_with("video/")
            || essence.starts_with("audio/"))
            && !essence.contains("xml"));
    if renders_natively {
        return essence.to_string();
    }

    let text_like = essence.starts_with("text/")
        || essence.ends_with("+json")
        || essence.ends_with("+xml")
        || matches!(
            essence,
            "application/json"
                | "application/xml"
                | "application/javascript"
                | "application/typescript"
                | "application/x-yaml"
                | "application/yaml"
                | "application/x-sh"
                | "application/sql"
                | "application/toml"
        );
    if text_like {
        return "text/plain; charset=utf-8".to_string();
    }

    "application/octet-stream".to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn keeps_specific_declared_type() {
        assert_eq!(
            resolve_mime_type("image/png", "photo.bin", None),
            "image/png"
        );
    }

    #[test]
    fn infers_type_for_generic_uploads() {
        assert_eq!(
            resolve_mime_type("video/mp2t", "main.ts", None),
            "application/typescript"
        );
        assert_eq!(
            resolve_mime_type("video/mp2t", "clip.m2ts", None),
            "video/mp2t"
        );
        assert_eq!(
            resolve_mime_type("application/octet-stream", "Report.PDF", None),
            "application/pdf"
        );
        assert_eq!(resolve_mime_type("", "main.rs", None), "text/plain");
        assert_eq!(resolve_mime_type("", "Dockerfile", None), "text/plain");
        assert_eq!(
            resolve_mime_type("application/octet-stream", "archive.unknownext", None),
            "application/octet-stream"
        );
    }

    #[test]
    fn inline_passes_through_renderable_media() {
        assert_eq!(
            inline_content_type("application/pdf", "a.pdf", None),
            "application/pdf"
        );
        assert_eq!(
            inline_content_type("image/jpeg", "a.jpg", None),
            "image/jpeg"
        );
        assert_eq!(inline_content_type("video/mp4", "a.mp4", None), "video/mp4");
        assert_eq!(
            inline_content_type("audio/mpeg", "a.mp3", None),
            "audio/mpeg"
        );
        assert_eq!(
            inline_content_type("application/octet-stream", "scan.pdf", None),
            "application/pdf"
        );
    }

    #[test]
    fn inline_downgrades_markup_and_code_to_plain_text() {
        assert_eq!(
            inline_content_type("image/svg+xml", "logo.svg", None),
            "text/plain; charset=utf-8"
        );
        assert_eq!(
            inline_content_type("video/mp2t", "main.ts", None),
            "text/plain; charset=utf-8"
        );
        let plain = "text/plain; charset=utf-8";
        assert_eq!(inline_content_type("text/html", "index.html", None), plain);
        assert_eq!(
            inline_content_type("application/json", "a.json", None),
            plain
        );
        assert_eq!(
            inline_content_type("application/xhtml+xml", "a.xhtml", None),
            plain
        );
        assert_eq!(inline_content_type("", "lib.py", None), plain);
    }

    #[test]
    fn mpeg_ts_video_keeps_video_type() {
        let mut stream = vec![0u8; 376];
        stream[0] = 0x47;
        stream[188] = 0x47;
        let source = b"export const answer: number = 42;\n";
        assert!(looks_like_mpeg_ts(&stream));
        assert!(!looks_like_mpeg_ts(source));
        assert!(!looks_like_mpeg_ts(b"GetUser();\n"));
        assert_eq!(
            resolve_mime_type("video/mp2t", "main.ts", Some(b"GetUser();\n")),
            "application/typescript"
        );
        assert_eq!(
            resolve_mime_type("video/mp2t", "clip.ts", Some(&stream)),
            "video/mp2t"
        );
        assert_eq!(
            inline_content_type("video/mp2t", "clip.ts", Some(&stream)),
            "video/mp2t"
        );
        assert_eq!(
            resolve_mime_type("video/mp2t", "main.ts", Some(source)),
            "application/typescript"
        );
    }

    #[test]
    fn inline_leaves_binary_types_opaque() {
        assert_eq!(
            inline_content_type("application/zip", "a.zip", None),
            "application/octet-stream"
        );
    }
}
