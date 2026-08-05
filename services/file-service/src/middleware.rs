use actix_web::dev::{Service, ServiceRequest, ServiceResponse, Transform};
use actix_web::Error;
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
    use actix_web::{test, web, App, HttpResponse};

    #[actix_web::test]
    async fn reuses_an_inbound_request_id_and_records_the_matched_pattern() {
        let app = test::init_service(App::new().wrap(RequestId).route(
            "/files/{id}",
            web::get().to(|| async { HttpResponse::Ok().body("ok") }),
        ))
        .await;

        let resp = test::call_service(
            &app,
            test::TestRequest::get()
                .uri("/files/42")
                .insert_header(("x-request-id", "caller-supplied"))
                .to_request(),
        )
        .await;

        assert_eq!(resp.status(), actix_web::http::StatusCode::OK);
        let rendered = render_metrics();
        assert!(rendered.contains("http_requests_total"), "{rendered}");
        assert!(rendered.contains("/files/{id}"), "{rendered}");
        assert!(
            rendered.contains("http_request_duration_seconds"),
            "{rendered}"
        );
    }

    #[actix_web::test]
    async fn labels_unrouted_requests_as_unmatched() {
        let app = test::init_service(App::new().wrap(RequestId)).await;

        let resp =
            test::call_service(&app, test::TestRequest::get().uri("/nope").to_request()).await;

        assert_eq!(resp.status(), actix_web::http::StatusCode::NOT_FOUND);
        assert!(render_metrics().contains("unmatched"));
    }

    #[actix_web::test]
    async fn counts_a_failing_handler_under_its_status_code() {
        let app = test::init_service(App::new().wrap(RequestId).route(
            "/boom",
            web::get().to(|| async { HttpResponse::InternalServerError().finish() }),
        ))
        .await;

        let resp =
            test::call_service(&app, test::TestRequest::get().uri("/boom").to_request()).await;

        assert_eq!(
            resp.status(),
            actix_web::http::StatusCode::INTERNAL_SERVER_ERROR
        );
        assert!(render_metrics().contains("status=\"500\""));
    }
}
