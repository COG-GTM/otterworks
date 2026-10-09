//! Bounded reading of the `POST /api/v1/files/upload` multipart body.
//!
//! The whole `file` part is buffered before it is sent to S3, so every byte a
//! request can make file-service hold is capped here: the raw body (part
//! headers included), the small id fields, discarded fields, the file part,
//! and the bytes buffered across all in-flight uploads (`UploadBudget`).

use std::cell::Cell;
use std::fmt::Display;
use std::rc::Rc;
use std::sync::Arc;

use actix_multipart::Multipart;
use actix_web::error::PayloadError;
use actix_web::http::header::{HeaderMap, CONTENT_LENGTH};
use bytes::{Bytes, BytesMut};
use futures_util::{Stream, StreamExt};
use tokio::sync::{OwnedSemaphorePermit, Semaphore};
use uuid::Uuid;

use crate::config::ServerConfig;
use crate::errors::ServiceError;

/// A hyphenated UUID is 36 bytes (45 with a `urn:uuid:` prefix); leave room
/// for surrounding whitespace and reject anything longer before buffering it.
pub const MAX_ID_FIELD_BYTES: usize = 64;

/// Allowance on top of `max_upload_bytes` for part headers, boundaries and
/// the small text fields; also the cap on discarded (unknown) field data.
pub const MULTIPART_OVERHEAD_BYTES: u64 = 64 * 1024;

/// Upper bound on parts per request.
pub const MAX_PARTS: usize = 16;

/// Granularity of the shared upload budget.
pub const BUDGET_UNIT_BYTES: u64 = 1024;

#[derive(Clone, Copy, Debug)]
pub struct UploadLimits {
    pub max_file_bytes: u64,
    pub max_body_bytes: u64,
}

impl UploadLimits {
    pub fn from_config(server: &ServerConfig) -> Self {
        Self {
            max_file_bytes: server.max_upload_bytes,
            max_body_bytes: server
                .max_upload_bytes
                .saturating_add(MULTIPART_OVERHEAD_BYTES),
        }
    }

    /// Rejects a request whose declared `Content-Length` already exceeds the
    /// body limit, before any of it is read.
    pub fn check_content_length(&self, content_length: Option<u64>) -> Result<(), ServiceError> {
        match content_length {
            Some(len) if len > self.max_body_bytes => Err(self.too_large(len)),
            _ => Ok(()),
        }
    }

    fn too_large(&self, actual_bytes: u64) -> ServiceError {
        ServiceError::FileTooLarge {
            max_bytes: self.max_file_bytes,
            actual_bytes,
        }
    }
}

/// Process-wide cap on the bytes buffered by concurrent uploads.
#[derive(Clone)]
pub struct UploadBudget {
    permits: Arc<Semaphore>,
}

impl UploadBudget {
    pub fn new(budget_bytes: u64) -> Self {
        let units = (budget_bytes / BUDGET_UNIT_BYTES).min(Semaphore::MAX_PERMITS as u64);
        Self {
            permits: Arc::new(Semaphore::new(units as usize)),
        }
    }

    pub fn reservation(&self) -> UploadReservation {
        UploadReservation {
            permits: self.permits.clone(),
            held: None,
            held_units: 0,
        }
    }
}

/// Budget held by one upload; released when dropped.
#[derive(Debug)]
pub struct UploadReservation {
    permits: Arc<Semaphore>,
    held: Option<OwnedSemaphorePermit>,
    held_units: u64,
}

impl UploadReservation {
    /// Grows the reservation to cover `bytes`, failing fast with 503 when the
    /// shared budget is exhausted.
    pub fn ensure(&mut self, bytes: u64) -> Result<(), ServiceError> {
        let needed = bytes.div_ceil(BUDGET_UNIT_BYTES);
        if needed <= self.held_units {
            return Ok(());
        }
        let extra = u32::try_from(needed - self.held_units)
            .map_err(|_| ServiceError::UploadCapacityExceeded)?;
        let permit = self
            .permits
            .clone()
            .try_acquire_many_owned(extra)
            .map_err(|_| ServiceError::UploadCapacityExceeded)?;
        match self.held.as_mut() {
            Some(held) => held.merge(permit),
            None => self.held = Some(permit),
        }
        self.held_units = needed;
        Ok(())
    }

    pub fn held_bytes(&self) -> u64 {
        self.held_units * BUDGET_UNIT_BYTES
    }
}

#[derive(Debug)]
pub struct UploadForm {
    pub file_bytes: BytesMut,
    pub file_name: String,
    pub content_type: String,
    pub owner_id: Option<Uuid>,
    pub folder_id: Option<Uuid>,
}

/// Raw request bytes read so far, counted before the multipart parser sees
/// them so part headers and boundaries are bounded too.
struct BodyGuard {
    read: Rc<Cell<u64>>,
    limits: UploadLimits,
}

impl BodyGuard {
    /// Maps a parser/stream error, reporting 413 when it was caused by the
    /// body limit.
    fn error(&self, e: impl Display) -> ServiceError {
        let read = self.read.get();
        if read > self.limits.max_body_bytes {
            self.limits.too_large(read)
        } else {
            ServiceError::BadRequest(e.to_string())
        }
    }
}

pub async fn read_upload_form<S>(
    headers: &HeaderMap,
    stream: S,
    limits: UploadLimits,
    reservation: &mut UploadReservation,
) -> Result<UploadForm, ServiceError>
where
    S: Stream<Item = Result<Bytes, PayloadError>> + 'static,
{
    let content_length = headers
        .get(CONTENT_LENGTH)
        .and_then(|v| v.to_str().ok())
        .and_then(|s| s.trim().parse::<u64>().ok());
    limits.check_content_length(content_length)?;

    // The file buffer is allocated once and never grows: a reallocation would
    // briefly hold both the old and the new buffer outside the budget. Without
    // a Content-Length the full per-file cap is reserved.
    let capacity =
        content_length.map_or(limits.max_file_bytes, |len| len.min(limits.max_file_bytes));
    reservation.ensure(capacity)?;

    let guard = BodyGuard {
        read: Rc::new(Cell::new(0)),
        limits,
    };
    let counter = guard.read.clone();
    let max_body = limits.max_body_bytes;
    let limited = stream.map(move |chunk| {
        let chunk = chunk?;
        let total = counter.get().saturating_add(chunk.len() as u64);
        counter.set(total);
        if total > max_body {
            return Err(PayloadError::Overflow);
        }
        Ok(chunk)
    });
    let mut payload = Multipart::new(headers, limited);

    let mut form = UploadForm {
        file_bytes: BytesMut::with_capacity(capacity as usize),
        file_name: String::from("unnamed"),
        content_type: String::from("application/octet-stream"),
        owner_id: None,
        folder_id: None,
    };
    let mut parts = 0usize;
    let mut discarded = 0u64;

    while let Some(item) = payload.next().await {
        let mut field = item.map_err(|e| guard.error(e))?;
        parts += 1;
        if parts > MAX_PARTS {
            return Err(ServiceError::BadRequest(format!(
                "too many multipart fields (max {MAX_PARTS})"
            )));
        }
        let disposition = field.content_disposition().cloned();
        let field_name = disposition
            .as_ref()
            .and_then(|d| d.get_name().map(|s| s.to_string()))
            .unwrap_or_default();

        match field_name.as_str() {
            "file" => {
                if let Some(fname) = disposition.as_ref().and_then(|d| d.get_filename()) {
                    form.file_name = fname.to_string();
                }
                if let Some(ct) = field.content_type() {
                    form.content_type = ct.to_string();
                }
                while let Some(chunk) = field.next().await {
                    let data = chunk.map_err(|e| guard.error(e))?;
                    let new_len = form.file_bytes.len() as u64 + data.len() as u64;
                    if new_len > limits.max_file_bytes {
                        return Err(limits.too_large(new_len));
                    }
                    if new_len > capacity {
                        return Err(ServiceError::BadRequest(
                            "body exceeds declared Content-Length".into(),
                        ));
                    }
                    form.file_bytes.extend_from_slice(&data);
                }
            }
            "owner_id" => {
                let raw = read_small_field(&mut field, "owner_id", &guard).await?;
                form.owner_id = Some(
                    raw.parse::<Uuid>()
                        .map_err(|e| ServiceError::BadRequest(format!("invalid owner_id: {e}")))?,
                );
            }
            "folder_id" => {
                let raw = read_small_field(&mut field, "folder_id", &guard).await?;
                if !raw.is_empty() {
                    form.folder_id = Some(raw.parse::<Uuid>().map_err(|e| {
                        ServiceError::BadRequest(format!("invalid folder_id: {e}"))
                    })?);
                }
            }
            _ => {
                // Unknown parts are discarded; keep them small so Content-Length
                // stays a close bound on the file size.
                while let Some(chunk) = field.next().await {
                    let data = chunk.map_err(|e| guard.error(e))?;
                    discarded += data.len() as u64;
                    if discarded > MULTIPART_OVERHEAD_BYTES {
                        return Err(ServiceError::BadRequest(format!(
                            "unexpected multipart fields exceed {MULTIPART_OVERHEAD_BYTES} bytes"
                        )));
                    }
                }
            }
        }
    }

    Ok(form)
}

async fn read_small_field(
    field: &mut actix_multipart::Field,
    name: &str,
    guard: &BodyGuard,
) -> Result<String, ServiceError> {
    let mut value = BytesMut::new();
    while let Some(chunk) = field.next().await {
        let data = chunk.map_err(|e| guard.error(e))?;
        if value.len() + data.len() > MAX_ID_FIELD_BYTES {
            return Err(ServiceError::BadRequest(format!(
                "{name} exceeds {MAX_ID_FIELD_BYTES} bytes"
            )));
        }
        value.extend_from_slice(&data);
    }
    Ok(String::from_utf8_lossy(&value).trim().to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use actix_web::error::PayloadError;
    use actix_web::http::header::{HeaderMap, HeaderValue, CONTENT_LENGTH, CONTENT_TYPE};
    use bytes::Bytes;
    use futures_util::stream::{self, LocalBoxStream};

    type Body = LocalBoxStream<'static, Result<Bytes, PayloadError>>;

    const BOUNDARY: &str = "otterworks-test-boundary";
    const OWNER: &str = "6f1c2c4e-1f7a-4a52-9d36-0d6a3a3c9b11";

    fn limits(max_file_bytes: u64) -> UploadLimits {
        UploadLimits {
            max_file_bytes,
            max_body_bytes: max_file_bytes + MULTIPART_OVERHEAD_BYTES,
        }
    }

    fn headers(content_length: Option<u64>) -> HeaderMap {
        let mut headers = HeaderMap::new();
        headers.insert(
            CONTENT_TYPE,
            HeaderValue::from_str(&format!("multipart/form-data; boundary={BOUNDARY}")).unwrap(),
        );
        if let Some(len) = content_length {
            headers.insert(CONTENT_LENGTH, HeaderValue::from(len));
        }
        headers
    }

    fn text_part(name: &str, value: &str) -> String {
        format!(
            "--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n"
        )
    }

    fn file_part(content: &[u8]) -> Vec<u8> {
        let mut part = format!(
            "--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"notes.txt\"\r\nContent-Type: text/plain\r\n\r\n"
        )
        .into_bytes();
        part.extend_from_slice(content);
        part.extend_from_slice(b"\r\n");
        part
    }

    fn closing() -> String {
        format!("--{BOUNDARY}--\r\n")
    }

    fn multipart_from_body(body: Vec<u8>) -> Body {
        // Small chunks so the field limits are hit mid-stream, as on a socket.
        let chunks: Vec<Result<Bytes, PayloadError>> = body
            .chunks(16)
            .map(|c| Ok(Bytes::copy_from_slice(c)))
            .collect();
        stream::iter(chunks).boxed_local()
    }

    /// A body that starts with `head` and then never ends: the reader must
    /// give up on its own rather than buffer until memory runs out. Each
    /// chunk is preceded by a `Pending`, as on a socket, so the parser hands
    /// out field data between reads.
    fn endless(head: String) -> Body {
        let filler = Bytes::from(vec![b'a'; 4096]);
        stream::once(async move { Ok(Bytes::from(head)) })
            .chain(stream::unfold(filler, |filler| async move {
                tokio::task::yield_now().await;
                Some((Ok(filler.clone()), filler))
            }))
            .boxed_local()
    }

    /// Like `endless`, but every poll is immediately ready, so the parser
    /// keeps reading ahead without yielding any field data.
    fn endless_ready(head: String) -> Body {
        let filler = Bytes::from(vec![b'a'; 4096]);
        stream::once(async move { Ok(Bytes::from(head)) })
            .chain(stream::repeat_with(move || Ok(filler.clone())))
            .boxed_local()
    }

    fn endless_text_part(name: &str) -> Body {
        endless(format!(
            "--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n"
        ))
    }

    async fn read(
        payload: Body,
        limits: UploadLimits,
        content_length: Option<u64>,
        budget: &UploadBudget,
    ) -> Result<(UploadForm, UploadReservation), ServiceError> {
        let mut reservation = budget.reservation();
        let form =
            read_upload_form(&headers(content_length), payload, limits, &mut reservation).await?;
        Ok((form, reservation))
    }

    fn big_budget() -> UploadBudget {
        UploadBudget::new(16 * 1024 * 1024)
    }

    #[actix_rt::test]
    async fn reads_a_normal_upload() {
        let mut body = text_part("owner_id", OWNER).into_bytes();
        body.extend(text_part("folder_id", "").into_bytes());
        body.extend(file_part(b"hello otterworks"));
        body.extend(closing().into_bytes());

        let (form, held) = read(multipart_from_body(body), limits(1024), None, &big_budget())
            .await
            .unwrap();
        assert_eq!(&form.file_bytes[..], b"hello otterworks");
        assert!(form.file_bytes.capacity() as u64 <= held.held_bytes());
        assert_eq!(form.file_name, "notes.txt");
        assert_eq!(form.content_type, "text/plain");
        assert_eq!(form.owner_id, Some(OWNER.parse().unwrap()));
        assert_eq!(form.folder_id, None);
    }

    #[actix_rt::test]
    async fn accepts_padded_uuid_within_limit() {
        let padded = format!("  {OWNER}  \n");
        let mut body = text_part("owner_id", &padded).into_bytes();
        body.extend(file_part(b"x"));
        body.extend(closing().into_bytes());
        let (form, _r) = read(multipart_from_body(body), limits(1024), None, &big_budget())
            .await
            .unwrap();
        assert_eq!(form.owner_id, Some(OWNER.parse().unwrap()));
    }

    #[actix_rt::test]
    async fn rejects_oversized_owner_id_without_buffering_it() {
        let err = read(
            endless_text_part("owner_id"),
            limits(1024),
            None,
            &big_budget(),
        )
        .await
        .unwrap_err();
        assert!(
            matches!(&err, ServiceError::BadRequest(m) if m.contains("owner_id exceeds")),
            "{err:?}"
        );
    }

    #[actix_rt::test]
    async fn rejects_oversized_folder_id_without_buffering_it() {
        let err = read(
            endless_text_part("folder_id"),
            limits(1024),
            None,
            &big_budget(),
        )
        .await
        .unwrap_err();
        assert!(
            matches!(&err, ServiceError::BadRequest(m) if m.contains("folder_id exceeds")),
            "{err:?}"
        );
    }

    #[actix_rt::test]
    async fn unknown_parts_are_capped() {
        let err = read(
            endless_text_part("padding"),
            limits(1024 * 1024),
            None,
            &big_budget(),
        )
        .await
        .unwrap_err();
        assert!(
            matches!(&err, ServiceError::BadRequest(m) if m.contains("unexpected multipart fields")),
            "{err:?}"
        );
    }

    #[actix_rt::test]
    async fn read_ahead_is_stopped_by_the_raw_body_limit() {
        let err = read(
            endless_ready(format!(
                "--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"owner_id\"\r\n\r\n"
            )),
            limits(1024),
            None,
            &big_budget(),
        )
        .await
        .unwrap_err();
        assert!(matches!(err, ServiceError::FileTooLarge { .. }), "{err:?}");
    }

    #[actix_rt::test]
    async fn part_headers_count_toward_the_body_limit() {
        // A part header that never terminates is buffered by the parser, not
        // returned as field data; the raw byte limit must still stop it.
        let err = read(
            endless(format!(
                "--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"file\"; x=\""
            )),
            limits(1024),
            None,
            &big_budget(),
        )
        .await
        .unwrap_err();
        assert!(
            matches!(
                err,
                ServiceError::FileTooLarge { .. } | ServiceError::BadRequest(_)
            ),
            "{err:?}"
        );
    }

    #[actix_rt::test]
    async fn reserves_from_content_length_when_declared() {
        let mut body = text_part("owner_id", OWNER).into_bytes();
        body.extend(file_part(b"small"));
        body.extend(closing().into_bytes());
        let len = body.len() as u64;
        let (form, held) = read(
            multipart_from_body(body),
            limits(1024 * 1024),
            Some(len),
            &big_budget(),
        )
        .await
        .unwrap();
        assert_eq!(&form.file_bytes[..], b"small");
        assert_eq!(
            held.held_bytes(),
            len.div_ceil(BUDGET_UNIT_BYTES) * BUDGET_UNIT_BYTES
        );
    }

    #[actix_rt::test]
    async fn reserves_the_file_cap_without_content_length() {
        let mut body = file_part(b"small");
        body.extend(closing().into_bytes());
        let (_form, held) = read(
            multipart_from_body(body),
            limits(1024 * 1024),
            None,
            &big_budget(),
        )
        .await
        .unwrap();
        assert_eq!(held.held_bytes(), 1024 * 1024);
    }

    #[actix_rt::test]
    async fn rejects_file_over_the_per_file_limit() {
        let mut body = file_part(&[b'z'; 2048]);
        body.extend(closing().into_bytes());
        let err = read(multipart_from_body(body), limits(1024), None, &big_budget())
            .await
            .unwrap_err();
        assert!(
            matches!(
                err,
                ServiceError::FileTooLarge {
                    max_bytes: 1024,
                    ..
                }
            ),
            "{err:?}"
        );
    }

    #[actix_rt::test]
    async fn rejects_declared_content_length_over_the_limit_before_reading() {
        // The stream would fail if polled: the request must be refused first.
        let payload =
            stream::once(async { Err::<Bytes, _>(PayloadError::Incomplete(None)) }).boxed_local();
        let err = read(payload, limits(1024), Some(10 * 1024 * 1024), &big_budget())
            .await
            .unwrap_err();
        assert!(matches!(err, ServiceError::FileTooLarge { .. }), "{err:?}");
    }

    #[actix_rt::test]
    async fn rejects_too_many_parts() {
        let mut body = Vec::new();
        for _ in 0..=MAX_PARTS {
            body.extend(text_part("extra", "1").into_bytes());
        }
        body.extend(closing().into_bytes());
        let err = read(multipart_from_body(body), limits(1024), None, &big_budget())
            .await
            .unwrap_err();
        assert!(
            matches!(&err, ServiceError::BadRequest(m) if m.contains("too many")),
            "{err:?}"
        );
    }

    #[actix_rt::test]
    async fn concurrent_uploads_share_the_memory_budget() {
        let budget = UploadBudget::new(64 * 1024);
        let file = vec![b'q'; 40 * 1024];
        let body = |content: &[u8]| {
            let mut body = file_part(content);
            body.extend(closing().into_bytes());
            body
        };

        let (first, held) = read(
            multipart_from_body(body(&file)),
            limits(48 * 1024),
            None,
            &budget,
        )
        .await
        .unwrap();
        assert_eq!(first.file_bytes.len(), file.len());
        assert!(held.held_bytes() >= file.len() as u64);

        // A second upload that would push buffered bytes past the budget is
        // refused with 503 while the first is still held...
        let err = read(
            multipart_from_body(body(&file)),
            limits(48 * 1024),
            None,
            &budget,
        )
        .await
        .unwrap_err();
        assert!(
            matches!(err, ServiceError::UploadCapacityExceeded),
            "{err:?}"
        );

        // ...and admitted once the first upload releases its reservation.
        drop(held);
        read(
            multipart_from_body(body(&file)),
            limits(48 * 1024),
            None,
            &budget,
        )
        .await
        .unwrap();
    }

    #[test]
    fn reservation_grows_and_releases() {
        let budget = UploadBudget::new(8 * 1024);
        let mut a = budget.reservation();
        a.ensure(3 * 1024).unwrap();
        a.ensure(6 * 1024).unwrap();
        assert_eq!(a.held_bytes(), 6 * 1024);
        let mut b = budget.reservation();
        assert!(matches!(
            b.ensure(4 * 1024),
            Err(ServiceError::UploadCapacityExceeded)
        ));
        drop(a);
        b.ensure(4 * 1024).unwrap();
    }

    #[test]
    fn capacity_error_maps_to_503() {
        use actix_web::ResponseError;
        assert_eq!(
            ServiceError::UploadCapacityExceeded
                .error_response()
                .status(),
            actix_web::http::StatusCode::SERVICE_UNAVAILABLE
        );
    }
}
