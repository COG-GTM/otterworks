module Api
  module V1
    module Admin
      class ChaosController < ApplicationController
        CHAOS_TTL_SECONDS = 600 # 10-minute auto-expiry so demo resets itself

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
          keys = redis.keys('chaos:*')
          redis.del(*keys) if keys.any?

          # Resolve only incidents the alert pipeline attributed to a chaos run
          # (ChaosIncidentRegistry), so the next run is not blocked by the dedup
          # guard. Incidents opened while no chaos flag was set stay untouched.
          resolved_incidents = []
          VALID_SCENARIOS.each_key do |svc|
            ids = ChaosIncidentRegistry.ids(redis, svc)
            next if ids.empty?

            Incident.active.where(id: ids, affected_service: svc).each do |incident|
              incident.resolve!
              resolved_incidents << incident.id
            rescue Incident::InvalidTransitionError => e
              Rails.logger.warn("CHAOS RESET: skipping incident #{incident.id}: #{e.message}")
            end
            redis.del(ChaosIncidentRegistry.key(svc))
          end

          Rails.logger.warn("CHAOS RESET by #{current_user_id}: cleared #{keys.size} flag(s): #{keys.join(', ')}; resolved #{resolved_incidents.size} incident(s)")

          render json: { status: 'reset', cleared: keys, resolved_incidents: resolved_incidents }
        end

        private

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
