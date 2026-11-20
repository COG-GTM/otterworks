package main

import (
	"context"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/go-chi/chi/v5"
	chimw "github.com/go-chi/chi/v5/middleware"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/redis/go-redis/v9"
	"github.com/rs/zerolog"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	semconv "go.opentelemetry.io/otel/semconv/v1.24.0"

	"github.com/Cognition-Partner-Workshops/otterworks/services/api-gateway/internal/config"
	"github.com/Cognition-Partner-Workshops/otterworks/services/api-gateway/internal/health"
	"github.com/Cognition-Partner-Workshops/otterworks/services/api-gateway/internal/middleware"
	"github.com/Cognition-Partner-Workshops/otterworks/services/api-gateway/internal/proxy"
)

func main() {
	cfg := config.Load()
	if err := cfg.Validate(); err != nil {
		l := zerolog.New(os.Stdout).With().Timestamp().Logger()
		l.Fatal().Err(err).Msg("invalid configuration")
	}

	// Structured JSON logging
	zerolog.TimeFieldFormat = zerolog.TimeFormatUnix
	logger := zerolog.New(os.Stdout).With().
		Timestamp().
		Str("service", "api-gateway").
		Logger()

	middleware.SetLogLevel(cfg.LogLevel)

	// OpenTelemetry tracing
	shutdownTracer := initTracer()

	// Circuit breaker manager
	cbManager := proxy.NewCircuitBreakerManager(proxy.CircuitBreakerConfig{
		MaxRequests:  cfg.CBMaxRequests,
		Interval:     cfg.CBInterval,
		Timeout:      cfg.CBTimeout,
		FailureRatio: cfg.CBFailureRatio,
	})

	// Build routes
	var routes []proxy.Route
	for prefix, target := range cfg.ServiceRoutes() {
		routes = append(routes, proxy.Route{
			Prefix:    prefix,
			TargetURL: target,
		})
	}

	// Create main router
	r := chi.NewRouter()

	// Global middleware stack
	r.Use(middleware.RequestID)
	r.Use(chimw.RealIP)
	r.Use(middleware.Metrics)
	r.Use(middleware.Logger(logger))
	r.Use(chimw.Recoverer)
	r.Use(chimw.Compress(5))

	// CORS runs before rate limiting so 429 responses carry CORS headers and
	// browsers can read Retry-After.
	r.Use(middleware.CORS(middleware.CORSConfig{
		AllowedOrigins:   cfg.CORSAllowedOrigins,
		AllowedMethods:   cfg.CORSAllowedMethods,
		AllowedHeaders:   cfg.CORSAllowedHeaders,
		ExposedHeaders:   []string{"Link", "X-Request-ID", "Retry-After", "X-RateLimit-Limit", "X-RateLimit-Remaining"},
		AllowCredentials: true,
		MaxAge:           cfg.CORSMaxAge,
	}))

	// Per-client rate limiting
	if cfg.RateLimitEnabled {
		rlMiddleware, closeRedis := newRateLimitMiddleware(cfg, logger)
		defer closeRedis()
		r.Use(rlMiddleware)
	}

	// JWT validation
	r.Use(middleware.JWTAuth(middleware.JWTConfig{
		Secret:              cfg.JWTSecret,
		PublicPath:          middleware.DefaultPublicPaths(),
		PrefixPath:          middleware.DefaultPrefixPaths(),
		ProtectedPrefixPath: routePrefixes(routes),
	}))

	// Health check
	r.Get("/health", health.Handler())

	// Prometheus metrics
	r.Handle("/metrics", promhttp.Handler())

	// Mount reverse proxy routes
	proxyRouter := proxy.NewRouter(proxy.RouterConfig{
		Routes:        routes,
		CBManager:     cbManager,
		Logger:        logger,
		EnableTracing: true,
	})
	r.Mount("/", proxyRouter)

	// HTTP server
	srv := &http.Server{
		Addr:         ":" + cfg.Port,
		Handler:      r,
		ReadTimeout:  15 * time.Second,
		WriteTimeout: 30 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	// Start server in background
	go func() {
		logger.Info().Str("port", cfg.Port).Msg("API Gateway starting")
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			logger.Fatal().Err(err).Msg("server failed")
		}
	}()

	// Graceful shutdown
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit
	logger.Info().Msg("shutting down server...")

	ctx, cancel := context.WithTimeout(context.Background(), cfg.ShutdownTimeout)
	defer cancel()

	if err := srv.Shutdown(ctx); err != nil {
		logger.Fatal().Err(err).Msg("server forced to shutdown")
	}

	if shutdownTracer != nil {
		if err := shutdownTracer(ctx); err != nil {
			logger.Error().Err(err).Msg("failed to shutdown tracer")
		}
	}

	logger.Info().Msg("server exited")
}

// newRateLimitMiddleware builds the rate limiter selected by RATE_LIMIT_BACKEND.
// The Redis backend falls back to a per-replica in-memory bucket while Redis
// is unreachable, so a Redis outage degrades the limit instead of the gateway.
func newRateLimitMiddleware(cfg *config.Config, logger zerolog.Logger) (func(http.Handler) http.Handler, func()) {
	memory := middleware.NewMemoryLimiter(cfg.RateLimitRPS, cfg.RateLimitBurst)
	rlCfg := middleware.RateLimitConfig{
		Limiter:        memory,
		Backend:        "memory",
		KeyFunc:        middleware.ClientKey(cfg.JWTSecret),
		ExemptPrefixes: []string{"/health", "/metrics"},
		Logger:         logger,
	}
	closeFn := func() {}

	if cfg.RateLimitBackend == "redis" {
		opts := &redis.Options{
			Addr:     net.JoinHostPort(cfg.RedisHost, cfg.RedisPort),
			Password: cfg.RedisPassword,
			DB:       cfg.RedisDB,
		}
		if cfg.RedisURL != "" {
			parsed, err := redis.ParseURL(cfg.RedisURL)
			if err != nil {
				logger.Fatal().Err(err).Msg("invalid RATE_LIMIT_REDIS_URL")
			}
			opts = parsed
		}
		client := redis.NewClient(opts)
		closeFn = func() { _ = client.Close() }

		rlCfg.Limiter = middleware.NewRedisLimiter(client, cfg.RateLimitRPS, cfg.RateLimitBurst, cfg.RateLimitKeyPrefix, cfg.RateLimitRedisTimeout)
		rlCfg.Backend = "redis"
		rlCfg.Fallback = memory

		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		if err := client.Ping(ctx).Err(); err != nil {
			logger.Warn().Err(err).Str("addr", opts.Addr).Msg("redis unreachable at startup; rate limiting falls back to in-memory until it recovers")
		}
		cancel()
	}

	logger.Info().
		Str("backend", rlCfg.Backend).
		Float64("rps", cfg.RateLimitRPS).
		Int("burst", cfg.RateLimitBurst).
		Msg("rate limiting enabled")
	return middleware.RateLimit(rlCfg), closeFn
}

func routePrefixes(routes []proxy.Route) []string {
	prefixes := make([]string, 0, len(routes))
	for _, route := range routes {
		prefixes = append(prefixes, route.Prefix)
	}
	return prefixes
}

// initTracer sets up the OpenTelemetry trace provider.
func initTracer() func(context.Context) error {
	ctx := context.Background()

	l := zerolog.New(os.Stdout).With().Timestamp().Logger()

	exporter, err := otlptracehttp.New(ctx)
	if err != nil {
		l.Warn().Err(err).Msg("failed to create OTLP exporter, tracing disabled")
		return nil
	}

	res, err := resource.New(ctx,
		resource.WithAttributes(
			semconv.ServiceName("api-gateway"),
			semconv.ServiceVersion("0.1.0"),
		),
	)
	if err != nil {
		exporter.Shutdown(ctx)
		l.Warn().Err(err).Msg("failed to create trace resource")
		return nil
	}

	tp := sdktrace.NewTracerProvider(
		sdktrace.WithBatcher(exporter),
		sdktrace.WithResource(res),
	)

	otel.SetTracerProvider(tp)
	otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(
		propagation.TraceContext{},
		propagation.Baggage{},
	))

	return tp.Shutdown
}
