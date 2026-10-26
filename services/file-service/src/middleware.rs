use actix_web::body::{EitherBody, MessageBody};
use actix_web::dev::{Service, ServiceRequest, ServiceResponse, Transform};
use actix_web::middleware::Next;
use actix_web::{web, Error, ResponseError};
use futures_util::future::{ok, LocalBoxFuture, Ready};
use std::task::{Context, Poll};
use uuid::Uuid;

use crate::config::AppConfig;
use crate::errors::ServiceError;
use crate::identity;

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

// -- Caller identity --

const INTERNAL_LISTING_PATH: &str = "/api/v1/files";

/// Rejects `/api/v1` requests without the gateway-injected `X-User-ID`, so a
/// caller that reaches file-service without the gateway cannot pick an
/// identity. The internal token is honoured only for the cross-owner file
/// listing (`GET /api/v1/files`) used by reindex crawls. Handlers still
/// resolve the owner themselves via `identity`.
pub async fn require_caller<B: MessageBody>(
    req: ServiceRequest,
    next: Next<B>,
) -> Result<ServiceResponse<EitherBody<B>>, Error> {
    let internal_token = req
        .app_data::<web::Data<AppConfig>>()
        .and_then(|config| config.server.internal_token.clone());
    let internal_listing = req.method() == actix_web::http::Method::GET
        && req.path() == INTERNAL_LISTING_PATH
        && identity::has_internal_token(req.headers(), internal_token.as_deref());
    if identity::caller_id(req.headers()).is_ok() || internal_listing {
        return next
            .call(req)
            .await
            .map(ServiceResponse::map_into_left_body);
    }
    let response =
        ServiceError::Unauthorized(format!("missing {} header", identity::USER_ID_HEADER))
            .error_response();
    Ok(req.into_response(response).map_into_right_body())
}

#[cfg(test)]
mod tests {
    use super::*;
    use actix_web::{middleware::from_fn, test, App, HttpResponse};

    const ALICE: &str = "11111111-1111-1111-1111-111111111111";

    async fn ok() -> HttpResponse {
        HttpResponse::Ok().finish()
    }

    fn config(internal_token: Option<&str>) -> web::Data<AppConfig> {
        let mut config = AppConfig::from_env();
        config.server.internal_token = internal_token.map(String::from);
        web::Data::new(config)
    }

    #[actix_rt::test]
    async fn rejects_requests_without_gateway_identity() {
        let app = test::init_service(
            App::new().app_data(config(Some("s3cret"))).service(
                web::scope("/api/v1/files")
                    .wrap(from_fn(require_caller))
                    .route("", web::get().to(ok)),
            ),
        )
        .await;

        let forged_owner = format!("/api/v1/files?owner_id={ALICE}");
        for uri in ["/api/v1/files", forged_owner.as_str()] {
            let resp =
                test::call_service(&app, test::TestRequest::get().uri(uri).to_request()).await;
            assert_eq!(
                resp.status(),
                actix_web::http::StatusCode::UNAUTHORIZED,
                "{uri}"
            );
        }

        let forged = test::TestRequest::get()
            .uri("/api/v1/files")
            .insert_header(("X-Internal-Token", "guess"))
            .to_request();
        let resp = test::call_service(&app, forged).await;
        assert_eq!(resp.status(), actix_web::http::StatusCode::UNAUTHORIZED);
    }

    #[actix_rt::test]
    async fn admits_gateway_identity_and_internal_token() {
        let app = test::init_service(
            App::new().app_data(config(Some("s3cret"))).service(
                web::scope("/api/v1/files")
                    .wrap(from_fn(require_caller))
                    .route("", web::get().to(ok))
                    .route("/{id}", web::get().to(ok))
                    .route("/{id}", web::delete().to(ok)),
            ),
        )
        .await;

        for req in [
            test::TestRequest::get().uri(&format!("/api/v1/files/{ALICE}")),
            test::TestRequest::delete().uri(&format!("/api/v1/files/{ALICE}")),
        ] {
            let resp = test::call_service(
                &app,
                req.insert_header(("X-Internal-Token", "s3cret"))
                    .to_request(),
            )
            .await;
            assert_eq!(resp.status(), actix_web::http::StatusCode::UNAUTHORIZED);
        }

        let user = test::TestRequest::get()
            .uri("/api/v1/files")
            .insert_header(("X-User-ID", ALICE))
            .to_request();
        assert!(test::call_service(&app, user).await.status().is_success());

        let internal = test::TestRequest::get()
            .uri("/api/v1/files")
            .insert_header(("X-Internal-Token", "s3cret"))
            .to_request();
        assert!(test::call_service(&app, internal)
            .await
            .status()
            .is_success());
    }
}
