#![allow(dead_code)]

use actix_web::middleware::from_fn;
use actix_web::{middleware as actix_middleware, web, App, HttpServer};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

mod alerts;
mod config;
mod errors;
mod events;
mod handlers;
mod metadata;
mod middleware;
mod models;
mod seed;
mod storage;

#[actix_web::main]
async fn main() -> std::io::Result<()> {
    dotenvy::dotenv().ok();

    tracing_subscriber::registry()
        .with(tracing_subscriber::EnvFilter::new(
            std::env::var("RUST_LOG")
                .unwrap_or_else(|_| "file_service=debug,actix_web=info".into()),
        ))
        .with(tracing_subscriber::fmt::layer().json())
        .init();

    let app_config = config::AppConfig::from_env();
    let s3_client = storage::S3Client::new(&app_config.aws).await;
    let meta_client = metadata::MetadataClient::new(&app_config.aws).await;
    let event_publisher = events::EventPublisher::new(&app_config.sns, &app_config.aws).await;

    let redis_url = {
        let host = std::env::var("REDIS_HOST").unwrap_or_else(|_| "localhost".into());
        let port = std::env::var("REDIS_PORT").unwrap_or_else(|_| "6379".into());
        format!("redis://{}:{}", host, port)
    };
    let redis_client = redis::Client::open(redis_url).expect("invalid Redis URL");
    let redis_cm = redis::aio::ConnectionManager::new(redis_client)
        .await
        .expect("failed to connect to Redis");

    let port = app_config.server.port;
    tracing::info!(port = %port, "File Service starting");

    let config_data = web::Data::new(app_config);
    let s3_data = web::Data::new(s3_client);
    let meta_data = web::Data::new(meta_client);
    let events_data = web::Data::new(event_publisher);
    let redis_data = web::Data::new(redis_cm);

    HttpServer::new(move || {
        App::new()
            .wrap(tracing_actix_web::TracingLogger::default())
            .wrap(actix_middleware::Compress::default())
            .wrap(middleware::RequestId)
            .app_data(config_data.clone())
            .app_data(s3_data.clone())
            .app_data(meta_data.clone())
            .app_data(events_data.clone())
            .app_data(redis_data.clone())
            .route("/health", web::get().to(handlers::health))
            .route("/metrics", web::get().to(handlers::metrics))
            .configure(api_routes)
    })
    .bind(format!("0.0.0.0:{port}"))?
    .run()
    .await
}

/// Every `/api/v1` route requires an authenticated caller; only `/health` and
/// `/metrics` are reachable without one.
fn api_routes(cfg: &mut web::ServiceConfig) {
    cfg.service(
        web::scope("/api/v1/files")
            .wrap(from_fn(middleware::require_caller))
            .route("/upload", web::post().to(handlers::upload_file))
            .route("/shared", web::get().to(handlers::list_shared_files))
            .route("/trash", web::get().to(handlers::list_trashed))
            .route("/activity", web::get().to(handlers::list_activity))
            .route("", web::get().to(handlers::list_files))
            .route("/{file_id}", web::get().to(handlers::get_file_metadata))
            .route("/{file_id}", web::delete().to(handlers::delete_file))
            .route(
                "/{file_id}/download",
                web::get().to(handlers::download_file),
            )
            .route("/{file_id}/move", web::put().to(handlers::move_file))
            .route("/{file_id}/rename", web::patch().to(handlers::rename_file))
            .route(
                "/{file_id}/versions",
                web::get().to(handlers::list_versions),
            )
            .route("/{file_id}/trash", web::post().to(handlers::trash_file))
            .route("/{file_id}/restore", web::post().to(handlers::restore_file))
            .route("/{file_id}/share", web::post().to(handlers::share_file))
            .route(
                "/{file_id}/share/{user_id}",
                web::delete().to(handlers::remove_share),
            ),
    )
    .service(
        web::scope("/api/v1/folders")
            .wrap(from_fn(middleware::require_caller))
            .route("", web::get().to(handlers::list_folders))
            .route("", web::post().to(handlers::create_folder))
            .route("/{folder_id}", web::get().to(handlers::get_folder))
            .route("/{folder_id}", web::put().to(handlers::update_folder))
            .route("/{folder_id}", web::delete().to(handlers::delete_folder)),
    );
}

#[cfg(test)]
mod tests {
    use super::*;
    use actix_web::http::Method;
    use actix_web::test;

    const FILE: &str = "6f1c8c1e-6a0e-4c43-9a51-5b0f3c1d2e4f";
    const USER: &str = "0b7f6c1a-2d3e-4f50-8a9b-c0d1e2f3a4b5";

    fn api_requests() -> Vec<(Method, String)> {
        vec![
            (Method::POST, "/api/v1/files/upload".into()),
            (Method::GET, "/api/v1/files/shared".into()),
            (Method::GET, "/api/v1/files/trash".into()),
            (Method::GET, "/api/v1/files/activity".into()),
            (Method::GET, "/api/v1/files".into()),
            (Method::GET, format!("/api/v1/files?owner_id={USER}")),
            (Method::GET, format!("/api/v1/files/{FILE}")),
            (Method::DELETE, format!("/api/v1/files/{FILE}")),
            (Method::GET, format!("/api/v1/files/{FILE}/download")),
            (Method::PUT, format!("/api/v1/files/{FILE}/move")),
            (Method::PATCH, format!("/api/v1/files/{FILE}/rename")),
            (Method::GET, format!("/api/v1/files/{FILE}/versions")),
            (Method::POST, format!("/api/v1/files/{FILE}/trash")),
            (Method::POST, format!("/api/v1/files/{FILE}/restore")),
            (Method::POST, format!("/api/v1/files/{FILE}/share")),
            (Method::DELETE, format!("/api/v1/files/{FILE}/share/{USER}")),
            (Method::GET, "/api/v1/folders".into()),
            (Method::POST, "/api/v1/folders".into()),
            (Method::GET, format!("/api/v1/folders/{FILE}")),
            (Method::PUT, format!("/api/v1/folders/{FILE}")),
            (Method::DELETE, format!("/api/v1/folders/{FILE}")),
        ]
    }

    #[actix_rt::test]
    async fn every_api_route_rejects_requests_without_caller_identity() {
        let app = test::init_service(App::new().configure(api_routes)).await;

        for (method, uri) in api_requests() {
            let anonymous = test::TestRequest::default()
                .method(method.clone())
                .uri(&uri)
                .to_request();
            let resp = test::call_service(&app, anonymous).await;
            assert_eq!(resp.status(), 401, "{method} {uri} without X-User-ID");

            let forged = test::TestRequest::default()
                .method(method.clone())
                .uri(&uri)
                .insert_header(("X-User-ID", "not-a-uuid"))
                .to_request();
            let resp = test::call_service(&app, forged).await;
            assert_eq!(resp.status(), 401, "{method} {uri} with invalid X-User-ID");
        }
    }

    #[actix_rt::test]
    async fn api_routes_admit_a_caller_with_identity() {
        let app = test::init_service(App::new().configure(api_routes)).await;

        for (method, uri) in api_requests() {
            let req = test::TestRequest::default()
                .method(method.clone())
                .uri(&uri)
                .insert_header(("X-User-ID", USER))
                .to_request();
            let resp = test::call_service(&app, req).await;
            assert_ne!(resp.status(), 401, "{method} {uri} with X-User-ID");
        }
    }
}
