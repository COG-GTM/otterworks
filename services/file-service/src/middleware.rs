use actix_web::body::{EitherBody, MessageBody};
use actix_web::dev::{Service, ServiceRequest, ServiceResponse, Transform};
use actix_web::http::header::HeaderMap;
use actix_web::middleware::Next;
use actix_web::{Error, ResponseError};
use futures_util::future::{ok, LocalBoxFuture, Ready};
use std::task::{Context, Poll};
use uuid::Uuid;

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

// -- Gateway Identity --

pub const USER_ID_HEADER: &str = "X-User-ID";
pub const MISSING_IDENTITY: &str = "missing or invalid X-User-ID header";

pub fn user_id_from_headers(headers: &HeaderMap) -> Option<Uuid> {
    headers
        .get(USER_ID_HEADER)
        .and_then(|v| v.to_str().ok())
        .and_then(|s| s.trim().parse::<Uuid>().ok())
}

/// Rejects any request that did not come through the api-gateway with an
/// authenticated identity, so direct callers cannot act as another user.
pub async fn require_user_id<B: MessageBody>(
    req: ServiceRequest,
    next: Next<B>,
) -> Result<ServiceResponse<EitherBody<B>>, Error> {
    if user_id_from_headers(req.headers()).is_none() {
        let resp =
            crate::errors::ServiceError::Unauthorized(MISSING_IDENTITY.into()).error_response();
        return Ok(req.into_response(resp).map_into_right_body());
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
    use actix_web::{http::StatusCode, test, web, App, HttpResponse};

    fn app() -> App<
        impl actix_web::dev::ServiceFactory<
            ServiceRequest,
            Config = (),
            Response = ServiceResponse<impl MessageBody>,
            Error = Error,
            InitError = (),
        >,
    > {
        App::new().service(
            web::scope("/api/v1/files")
                .wrap(actix_web::middleware::from_fn(require_user_id))
                .route("", web::get().to(HttpResponse::Ok)),
        )
    }

    #[actix_rt::test]
    async fn rejects_query_owner_id_without_gateway_header() {
        let svc = test::init_service(app()).await;
        let req = test::TestRequest::get()
            .uri(&format!("/api/v1/files?owner_id={}", Uuid::new_v4()))
            .to_request();
        let resp = test::call_service(&svc, req).await;
        assert_eq!(resp.status(), StatusCode::UNAUTHORIZED);
    }

    #[actix_rt::test]
    async fn rejects_invalid_gateway_header() {
        let svc = test::init_service(app()).await;
        let req = test::TestRequest::get()
            .uri("/api/v1/files")
            .insert_header((USER_ID_HEADER, "not-a-uuid"))
            .to_request();
        let resp = test::call_service(&svc, req).await;
        assert_eq!(resp.status(), StatusCode::UNAUTHORIZED);
    }

    #[actix_rt::test]
    async fn allows_request_with_gateway_header() {
        let svc = test::init_service(app()).await;
        let req = test::TestRequest::get()
            .uri("/api/v1/files")
            .insert_header((USER_ID_HEADER, Uuid::new_v4().to_string()))
            .to_request();
        let resp = test::call_service(&svc, req).await;
        assert_eq!(resp.status(), StatusCode::OK);
    }
}
