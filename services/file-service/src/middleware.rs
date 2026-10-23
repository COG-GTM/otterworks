use actix_web::body::{EitherBody, MessageBody};
use actix_web::dev::{Service, ServiceRequest, ServiceResponse, Transform};
use actix_web::http::header::HeaderMap;
use actix_web::middleware::Next;
use actix_web::Error;
use futures_util::future::{ok, LocalBoxFuture, Ready};
use std::task::{Context, Poll};
use uuid::Uuid;

use crate::errors::ServiceError;
use lazy_static::lazy_static;
use prometheus::{
    register_histogram_vec, register_int_counter_vec, Encoder, HistogramVec, IntCounterVec,
    TextEncoder,
};

lazy_static! {
    pub static ref HTTP_REQUESTS_TOTAL: IntCounterVec = register_int_counter_vec!(
        "http_requests_total",
        "Total HTTP requests",
        &["method", "path", "status"]
    )
    .expect("metric can be created");
    pub static ref HTTP_REQUEST_DURATION: HistogramVec = register_histogram_vec!(
        "http_request_duration_seconds",
        "HTTP request duration in seconds",
        &["method", "path"],
        vec![0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
    )
    .expect("metric can be created");
}

pub fn render_metrics() -> String {
    let encoder = TextEncoder::new();
    let metric_families = prometheus::gather();
    let mut buffer = Vec::new();
    encoder.encode(&metric_families, &mut buffer).unwrap();
    String::from_utf8(buffer).unwrap()
}

// -- Caller Identity --

pub const USER_ID_HEADER: &str = "X-User-ID";

/// The authenticated caller, from the `X-User-ID` header the api-gateway sets
/// from the validated JWT. A request without it is unauthenticated and must
/// not fall back to any caller-supplied owner.
pub fn caller_from_headers(headers: &HeaderMap) -> Result<Uuid, ServiceError> {
    let value = headers
        .get(USER_ID_HEADER)
        .ok_or_else(|| ServiceError::Unauthorized("missing X-User-ID header".into()))?;
    value
        .to_str()
        .ok()
        .and_then(|s| s.trim().parse::<Uuid>().ok())
        .ok_or_else(|| ServiceError::Unauthorized("invalid X-User-ID header".into()))
}

/// Rejects any request that carries no valid caller identity before it reaches
/// a handler, so no route can run unscoped. The rejection is returned as a 401
/// response (not an `Err`) so outer middleware still logs and counts it.
pub async fn require_caller(
    req: ServiceRequest,
    next: Next<impl MessageBody>,
) -> Result<ServiceResponse<EitherBody<impl MessageBody>>, Error> {
    if let Err(err) = caller_from_headers(req.headers()) {
        return Ok(req.error_response(err).map_into_right_body());
    }
    next.call(req)
        .await
        .map(ServiceResponse::map_into_left_body)
}

// -- Request ID Middleware --

pub struct RequestId;

impl<S, B> Transform<S, ServiceRequest> for RequestId
where
    S: Service<ServiceRequest, Response = ServiceResponse<B>, Error = Error>,
    S::Future: 'static,
    B: 'static,
{
    type Response = ServiceResponse<B>;
    type Error = Error;
    type Transform = RequestIdMiddleware<S>;
    type InitError = ();
    type Future = Ready<Result<Self::Transform, Self::InitError>>;

    fn new_transform(&self, service: S) -> Self::Future {
        ok(RequestIdMiddleware { service })
    }
}

pub struct RequestIdMiddleware<S> {
    service: S,
}

impl<S, B> Service<ServiceRequest> for RequestIdMiddleware<S>
where
    S: Service<ServiceRequest, Response = ServiceResponse<B>, Error = Error>,
    S::Future: 'static,
    B: 'static,
{
    type Response = ServiceResponse<B>;
    type Error = Error;
    type Future = LocalBoxFuture<'static, Result<Self::Response, Self::Error>>;

    fn poll_ready(&self, cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        self.service.poll_ready(cx)
    }

    fn call(&self, req: ServiceRequest) -> Self::Future {
        let request_id = req
            .headers()
            .get("x-request-id")
            .and_then(|v| v.to_str().ok())
            .map(|s| s.to_string())
            .unwrap_or_else(|| Uuid::new_v4().to_string());

        let method = req.method().to_string();
        let path = req
            .match_pattern()
            .unwrap_or_else(|| "unmatched".to_string());
        let start = std::time::Instant::now();

        let fut = self.service.call(req);

        Box::pin(async move {
            let res = fut.await?;
            let elapsed = start.elapsed().as_secs_f64();
            let status = res.status().as_u16().to_string();

            HTTP_REQUESTS_TOTAL
                .with_label_values(&[&method, &path, &status])
                .inc();
            HTTP_REQUEST_DURATION
                .with_label_values(&[&method, &path])
                .observe(elapsed);

            tracing::info!(
                request_id = %request_id,
                method = %method,
                path = %path,
                status = %status,
                duration_ms = %(elapsed * 1000.0),
                "Request completed"
            );

            Ok(res)
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use actix_web::{middleware::from_fn, test, web, App, HttpResponse};

    #[actix_rt::test]
    async fn require_caller_rejects_missing_and_invalid_identity() {
        let app = test::init_service(
            App::new()
                .wrap(RequestId)
                .route("/health", web::get().to(HttpResponse::Ok))
                .service(
                    web::scope("/api")
                        .wrap(from_fn(require_caller))
                        .route("", web::get().to(HttpResponse::Ok)),
                ),
        )
        .await;

        let anonymous =
            test::call_service(&app, test::TestRequest::get().uri("/api").to_request()).await;
        assert_eq!(anonymous.status(), 401);
        let body: serde_json::Value = test::read_body_json(anonymous).await;
        assert_eq!(body["error"], "unauthorized");
        assert!(render_metrics().contains(r#"status="401""#));

        let invalid = test::call_service(
            &app,
            test::TestRequest::get()
                .uri("/api")
                .insert_header((USER_ID_HEADER, "not-a-uuid"))
                .to_request(),
        )
        .await;
        assert_eq!(invalid.status(), 401);

        let caller = test::call_service(
            &app,
            test::TestRequest::get()
                .uri("/api")
                .insert_header((USER_ID_HEADER, Uuid::new_v4().to_string()))
                .to_request(),
        )
        .await;
        assert_eq!(caller.status(), 200);

        let health =
            test::call_service(&app, test::TestRequest::get().uri("/health").to_request()).await;
        assert_eq!(health.status(), 200);
    }
}
