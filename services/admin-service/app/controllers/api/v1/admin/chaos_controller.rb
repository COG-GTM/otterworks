module Api
  module V1
    module Admin
      class ChaosController < ApplicationController
        CHAOS_TTL_SECONDS = 600 # 10-minute auto-expiry so demo resets itself
        # How long after a trigger the alert pipeline may still open an incident
        # that `reset` treats as chaos-created.
        CHAOS_WINDOW_TTL_SECONDS = 3600

        VALID_SCENARIOS = {
          'search-service'       => 'suggest_500',
          'file-service'         => 'upload_s3_error',
          'notification-service' => 'consumer_strict_schema',
          'document-service'     => 'slow_queries',
        }.freeze

        before_action :require_admin!
        before_action :verify_chaos_secret

        # POST /api/v1/admin/chaos
        # Body: { service: "search-service", scenario: "suggest_500" }
        def trigger
          svc      = params[:service].to_s
          scenario = params[:scenario].to_s

          unless VALID_SCENARIOS[svc] == scenario
            return render json: {
              error:    'Invalid service/scenario combination',
              valid:    VALID_SCENARIOS,
            }, status: :unprocessable_entity
          end

          redis_key = "chaos:#{svc}:#{scenario}"
          redis.setex(redis_key, CHAOS_TTL_SECONDS, '1')
          record_chaos_window(svc)

          # Start background probe to generate traffic → Prometheus metrics → Grafana alert
          ChaosProbeService.start(service: svc, redis_key: redis_key)

          Rails.logger.warn("CHAOS TRIGGERED: #{redis_key} (TTL #{CHAOS_TTL_SECONDS}s) by #{current_user_id}")

          render json: {
            status:     'chaos_active',
            key:        redis_key,
            expires_in: CHAOS_TTL_SECONDS,
          }
        end

        # DELETE /api/v1/admin/chaos
        def reset
          windows = VALID_SCENARIOS.keys.index_with { |svc| redis.get(chaos_window_key(svc)) }.compact

          keys = redis.keys('chaos:*')
          redis.del(*keys) if keys.any?
          window_keys = windows.keys.map { |svc| chaos_window_key(svc) }
          redis.del(*window_keys) if window_keys.any?

          # Resolve only the incidents the alert pipeline opened while chaos was
          # active, so the next run is not blocked by the dedup guard. Incidents
          # filed by people, or opened before the trigger, stay untouched.
          resolved_incidents = []
          windows.each do |svc, started_at|
            chaos_incidents(svc, started_at).each do |incident|
              incident.resolve!
              resolved_incidents << incident.id
            rescue Incident::InvalidTransitionError => e
              Rails.logger.warn("CHAOS RESET: skipping incident #{incident.id}: #{e.message}")
            end
          end

          Rails.logger.warn("CHAOS RESET by #{current_user_id}: cleared #{keys.size} flag(s): #{keys.join(', ')}; resolved #{resolved_incidents.size} incident(s)")

          render json: { status: 'reset', cleared: keys, resolved_incidents: resolved_incidents }
        end

        private

        def chaos_window_key(svc)
          "chaos_window:#{svc}"
        end

        # Keeps the earliest trigger time of the current chaos run per service.
        def record_chaos_window(svc)
          key = chaos_window_key(svc)
          return if redis.set(key, Time.current.to_i.to_s, nx: true, ex: CHAOS_WINDOW_TTL_SECONDS)

          redis.expire(key, CHAOS_WINDOW_TTL_SECONDS)
        end

        def chaos_incidents(svc, started_at)
          source = "%#{Incident.sanitize_sql_like(AlertsController::AUTO_INCIDENT_SOURCE)}%"
          Incident.active
                  .where(affected_service: svc, reporter_id: nil)
                  .where('created_at >= ?', Time.zone.at(started_at.to_i))
                  .where('description LIKE ?', source)
        end

        def redis
          @redis ||= begin
            url = ServiceEnv.redis_url
            Redis.new(url: url, timeout: 2)
          end
        end

        # Optional second factor for scripted callers. The admin JWT is always
        # required; when CHAOS_SECRET is set the header must match it too.
        def verify_chaos_secret
          expected = ENV.fetch('CHAOS_SECRET', nil).to_s
          return if expected.empty?

          provided = request.headers['X-Chaos-Secret']
          return if ActiveSupport::SecurityUtils.secure_compare(provided.to_s, expected)

          render json: { error: 'Unauthorized' }, status: :unauthorized
        end
      end
    end
  end
end
