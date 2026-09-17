//! Filename and content-type validation for uploads.
//!
//! Uploaded filenames and `Content-Type` headers are attacker-controlled. The
//! stored name is derived from the client filename and the stored MIME type is
//! echoed back on download (and used as the S3 object's `Content-Type`), so
//! both are constrained here: the name is reduced to a safe basename with an
//! extension drawn from an allowlist, and the MIME type is derived from that
//! extension rather than from the client's claim.

use crate::errors::ServiceError;

/// Extensions accepted by default, with the MIME type served for each.
/// Formats browsers execute in the origin's context (`html`, `svg`, `js`, …)
/// and native executables are deliberately absent.
const EXTENSION_MIME_TYPES: &[(&str, &str)] = &[
    ("txt", "text/plain"),
    ("log", "text/plain"),
    ("md", "text/markdown"),
    ("csv", "text/csv"),
    ("json", "application/json"),
    ("xml", "application/xml"),
    ("yaml", "application/yaml"),
    ("yml", "application/yaml"),
    ("pdf", "application/pdf"),
    ("rtf", "application/rtf"),
    ("doc", "application/msword"),
    (
        "docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    ("xls", "application/vnd.ms-excel"),
    (
        "xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
    ("ppt", "application/vnd.ms-powerpoint"),
    (
        "pptx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ),
    ("odt", "application/vnd.oasis.opendocument.text"),
    ("ods", "application/vnd.oasis.opendocument.spreadsheet"),
    ("odp", "application/vnd.oasis.opendocument.presentation"),
    ("png", "image/png"),
    ("jpg", "image/jpeg"),
    ("jpeg", "image/jpeg"),
    ("gif", "image/gif"),
    ("webp", "image/webp"),
    ("bmp", "image/bmp"),
    ("tif", "image/tiff"),
    ("tiff", "image/tiff"),
    ("mp3", "audio/mpeg"),
    ("wav", "audio/wav"),
    ("mp4", "video/mp4"),
    ("mov", "video/quicktime"),
    ("zip", "application/zip"),
    ("gz", "application/gzip"),
    ("tar", "application/x-tar"),
];

/// Longest stored filename, in bytes.
const MAX_FILE_NAME_BYTES: usize = 255;

/// A filename and content type that are safe to persist and serve.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ValidatedUpload {
    pub file_name: String,
    pub content_type: String,
}

/// Default allowlist, used when `UPLOAD_ALLOWED_EXTENSIONS` is unset.
pub fn default_allowed_extensions() -> Vec<String> {
    EXTENSION_MIME_TYPES
        .iter()
        .map(|(ext, _)| (*ext).to_string())
        .collect()
}

/// Parse a comma-separated extension allowlist (`"pdf, .PNG"` → `["pdf", "png"]`).
///
/// Entries outside `EXTENSION_MIME_TYPES` are dropped, so configuration can only
/// narrow the default allowlist, never widen it to a type with no known-safe
/// content type.
pub fn parse_allowed_extensions(raw: &str) -> Vec<String> {
    raw.split(',')
        .map(|part| part.trim().trim_start_matches('.').to_ascii_lowercase())
        .filter(|part| EXTENSION_MIME_TYPES.iter().any(|(ext, _)| *ext == part))
        .collect()
}

/// Reduce a client-supplied filename to a basename with no path segments,
/// control characters, or trailing dots/spaces.
fn sanitize_file_name(raw: &str) -> Result<String, ServiceError> {
    let basename = raw.rsplit(['/', '\\']).next().unwrap_or_default();

    let cleaned: String = basename
        .chars()
        .filter(|c| !c.is_control())
        .collect::<String>()
        .trim()
        .trim_end_matches(['.', ' '])
        .to_string();

    if cleaned.is_empty() {
        return Err(ServiceError::BadRequest("invalid file name".into()));
    }
    if cleaned.len() > MAX_FILE_NAME_BYTES {
        return Err(ServiceError::BadRequest(format!(
            "file name exceeds {MAX_FILE_NAME_BYTES} bytes"
        )));
    }

    Ok(cleaned)
}

/// Validate a client-supplied filename and content type against `allowed`.
///
/// Returns the name to store and the content type to serve. The client's
/// declared content type is never trusted: it is replaced by the type mapped
/// to the (allowlisted) extension.
pub fn validate_upload(
    raw_file_name: Option<&str>,
    allowed: &[String],
) -> Result<ValidatedUpload, ServiceError> {
    let raw = raw_file_name
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .ok_or_else(|| ServiceError::BadRequest("file name is required".into()))?;

    let file_name = sanitize_file_name(raw)?;

    let extension = file_name
        .rsplit_once('.')
        .map(|(_, ext)| ext.to_ascii_lowercase())
        .filter(|ext| !ext.is_empty())
        .ok_or_else(|| {
            ServiceError::BadRequest("file name must include a supported extension".into())
        })?;

    let content_type = EXTENSION_MIME_TYPES
        .iter()
        .find(|(ext, _)| *ext == extension)
        .map(|(_, mime)| (*mime).to_string())
        .filter(|_| allowed.contains(&extension))
        .ok_or_else(|| {
            ServiceError::BadRequest(format!("file type .{extension} is not allowed"))
        })?;

    Ok(ValidatedUpload {
        file_name,
        content_type,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn allowed() -> Vec<String> {
        default_allowed_extensions()
    }

    #[test]
    fn accepts_a_document_and_derives_its_content_type() {
        let result = validate_upload(Some("report.PDF"), &allowed()).unwrap();
        assert_eq!(result.file_name, "report.PDF");
        assert_eq!(result.content_type, "application/pdf");
    }

    #[test]
    fn rejects_executable_and_scriptable_extensions() {
        for name in [
            "payload.exe",
            "shell.php",
            "stored-xss.html",
            "stored-xss.svg",
            "drive-by.js",
            "macro.sh",
        ] {
            let err = validate_upload(Some(name), &allowed()).unwrap_err();
            assert!(
                matches!(&err, ServiceError::BadRequest(_)),
                "name={name} err={err}"
            );
        }
    }

    #[test]
    fn rejects_extension_hidden_behind_trailing_dots_or_spaces() {
        for name in ["shell.php.", "shell.php ", "shell.php . ."] {
            let err = validate_upload(Some(name), &allowed()).unwrap_err();
            assert!(
                matches!(&err, ServiceError::BadRequest(_)),
                "name={name} err={err}"
            );
        }
    }

    #[test]
    fn strips_path_segments_from_the_stored_name() {
        let result = validate_upload(Some("../../etc/passwd.txt"), &allowed()).unwrap();
        assert_eq!(result.file_name, "passwd.txt");

        let result = validate_upload(Some("C:\\windows\\notes.txt"), &allowed()).unwrap();
        assert_eq!(result.file_name, "notes.txt");
    }

    #[test]
    fn rejects_names_without_a_usable_extension() {
        for name in ["", "   ", "README", "..", "/", "photo.png/../"] {
            let err = validate_upload(Some(name), &allowed()).unwrap_err();
            assert!(
                matches!(&err, ServiceError::BadRequest(_)),
                "name={name} err={err}"
            );
        }
        let err = validate_upload(None, &allowed()).unwrap_err();
        assert!(matches!(&err, ServiceError::BadRequest(_)), "err={err}");
    }

    #[test]
    fn rejects_control_characters_and_overlong_names() {
        let err = validate_upload(Some("evil.txt\u{0}.php"), &allowed()).unwrap_err();
        assert!(matches!(&err, ServiceError::BadRequest(_)), "err={err}");

        let long = format!("{}.txt", "a".repeat(MAX_FILE_NAME_BYTES));
        let err = validate_upload(Some(&long), &allowed()).unwrap_err();
        assert!(matches!(&err, ServiceError::BadRequest(_)), "err={err}");
    }

    #[test]
    fn content_type_follows_the_extension_not_the_client() {
        let result = validate_upload(Some("avatar.png"), &allowed()).unwrap();
        assert_eq!(result.content_type, "image/png");
    }

    #[test]
    fn honors_a_narrowed_allowlist() {
        let narrow = parse_allowed_extensions(" .PDF , png , exe ");
        assert_eq!(narrow, vec!["pdf".to_string(), "png".to_string()]);
        assert!(validate_upload(Some("a.exe"), &narrow).is_err());
        assert!(validate_upload(Some("a.pdf"), &narrow).is_ok());
        assert!(validate_upload(Some("a.txt"), &narrow).is_err());
    }
}
