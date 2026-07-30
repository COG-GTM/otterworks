//! `middleware::RequestId` and the Prometheus metric rendering.

use actix_web::{test, web, App, HttpResponse};
use file_service::middleware::{render_metrics, RequestId, HTTP_REQUESTS_TOTAL};

fn counter(method: &str, path: &str, status: &str) -> u64 {
    HTTP_REQUESTS_TOTAL
        .with_label_values(&[method, path, status])
        .get()
}

#[actix_web::test]
async fn a_matched_request_is_counted_under_its_route_pattern() {
    let before = counter("GET", "/files/{id}", "200");
    let app = test::init_service(
        App::new()
            .wrap(RequestId)
            .route("/files/{id}", web::get().to(HttpResponse::Ok)),
    )
    .await;

    let resp = test::call_service(
        &app,
        test::TestRequest::get().uri("/files/abc").to_request(),
    )
    .await;

    assert!(resp.status().is_success());
    assert_eq!(
        counter("GET", "/files/{id}", "200"),
        before + 1,
        "the route pattern, not the concrete path, is the metric label"
    );
    assert_eq!(
        counter("GET", "/files/abc", "200"),
        0,
        "concrete ids must not explode the label cardinality"
    );
}

#[actix_web::test]
async fn an_unmatched_request_is_counted_as_unmatched() {
    let before = counter("GET", "unmatched", "404");
    let app = test::init_service(
        App::new()
            .wrap(RequestId)
            .route("/known", web::get().to(HttpResponse::Ok)),
    )
    .await;

    let resp = test::call_service(
        &app,
        test::TestRequest::get().uri("/nothing-here").to_request(),
    )
    .await;

    assert_eq!(resp.status().as_u16(), 404);
    assert_eq!(counter("GET", "unmatched", "404"), before + 1);
}

#[actix_web::test]
async fn the_response_status_is_part_of_the_metric_label() {
    let before = counter("POST", "/boom", "500");
    let app = test::init_service(
        App::new()
            .wrap(RequestId)
            .route("/boom", web::post().to(HttpResponse::InternalServerError)),
    )
    .await;

    let resp = test::call_service(&app, test::TestRequest::post().uri("/boom").to_request()).await;

    assert_eq!(resp.status().as_u16(), 500);
    assert_eq!(counter("POST", "/boom", "500"), before + 1);
}

#[actix_web::test]
async fn a_caller_supplied_request_id_is_accepted() {
    let before = counter("GET", "/traced", "200");
    let app = test::init_service(
        App::new()
            .wrap(RequestId)
            .route("/traced", web::get().to(HttpResponse::Ok)),
    )
    .await;

    let resp = test::call_service(
        &app,
        test::TestRequest::get()
            .uri("/traced")
            .insert_header(("x-request-id", "trace-me"))
            .to_request(),
    )
    .await;

    assert!(resp.status().is_success());
    assert_eq!(counter("GET", "/traced", "200"), before + 1);
}

#[actix_web::test]
async fn render_metrics_emits_the_prometheus_text_exposition_format() {
    let app = test::init_service(
        App::new()
            .wrap(RequestId)
            .route("/rendered", web::get().to(HttpResponse::Ok)),
    )
    .await;
    test::call_service(&app, test::TestRequest::get().uri("/rendered").to_request()).await;

    let rendered = render_metrics();

    assert!(
        rendered.contains("# TYPE http_requests_total counter"),
        "{rendered}"
    );
    assert!(
        rendered.contains(r#"http_requests_total{method="GET",path="/rendered",status="200"} 1"#),
        "{rendered}"
    );
    assert!(
        rendered.contains("http_request_duration_seconds_bucket"),
        "the latency histogram is exported too"
    );
}
