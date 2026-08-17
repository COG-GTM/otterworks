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

    async fn ok_handler() -> HttpResponse {
        HttpResponse::Ok().body("ok")
    }

    #[actix_web::test]
    async fn request_id_middleware_passes_the_response_through() {
        let app = test::init_service(
            App::new()
                .wrap(RequestId)
                .route("/thing/{id}", web::get().to(ok_handler)),
        )
        .await;

        let resp =
            test::call_service(&app, test::TestRequest::get().uri("/thing/42").to_request()).await;

        assert_eq!(resp.status(), actix_web::http::StatusCode::OK);
    }

    #[actix_web::test]
    async fn request_id_middleware_counts_requests_per_route_pattern() {
        let app = test::init_service(
            App::new()
                .wrap(RequestId)
                .route("/counted/{id}", web::get().to(ok_handler)),
        )
        .await;

        let before = HTTP_REQUESTS_TOTAL
            .with_label_values(&["GET", "/counted/{id}", "200"])
            .get();

        // An explicit request id is accepted, and a missing one is generated.
        let with_header = test::TestRequest::get()
            .uri("/counted/7")
            .insert_header(("x-request-id", "abc-123"))
            .to_request();
        assert!(test::call_service(&app, with_header)
            .await
            .status()
            .is_success());
        let without_header = test::TestRequest::get().uri("/counted/8").to_request();
        assert!(test::call_service(&app, without_header)
            .await
            .status()
            .is_success());

        let after = HTTP_REQUESTS_TOTAL
            .with_label_values(&["GET", "/counted/{id}", "200"])
            .get();
        assert_eq!(after - before, 2, "both requests are counted once each");

        let observations = HTTP_REQUEST_DURATION
            .with_label_values(&["GET", "/counted/{id}"])
            .get_sample_count();
        assert!(observations >= 2, "latency is observed per request");
    }

    #[actix_web::test]
    async fn unmatched_routes_are_counted_under_a_placeholder_path() {
        let app = test::init_service(
            App::new()
                .wrap(RequestId)
                .route("/known", web::get().to(ok_handler)),
        )
        .await;

        let before = HTTP_REQUESTS_TOTAL
            .with_label_values(&["GET", "unmatched", "404"])
            .get();
        let resp =
            test::call_service(&app, test::TestRequest::get().uri("/nope").to_request()).await;
        assert_eq!(resp.status(), actix_web::http::StatusCode::NOT_FOUND);
        let after = HTTP_REQUESTS_TOTAL
            .with_label_values(&["GET", "unmatched", "404"])
            .get();

        assert_eq!(after - before, 1);
    }

    #[actix_web::test]
    async fn render_metrics_emits_the_prometheus_text_exposition_format() {
        let app = test::init_service(
            App::new()
                .wrap(RequestId)
                .route("/rendered", web::get().to(ok_handler)),
        )
        .await;
        test::call_service(&app, test::TestRequest::get().uri("/rendered").to_request()).await;

        let rendered = render_metrics();

        assert!(
            rendered.contains("# TYPE http_requests_total counter"),
            "{rendered}"
        );
        assert!(rendered.contains("path=\"/rendered\""), "{rendered}");
        assert!(
            rendered.contains("http_request_duration_seconds_bucket"),
            "{rendered}"
        );
    }
}
