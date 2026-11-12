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

        # Both factors are always required: an admin JWT (role checked here; the
        # token itself by JwtAuthenticator) and the X-Chaos-Secret header. An
        # unset CHAOS_SECRET disables the endpoint instead of opening it.
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

          Rails.logger.warn("CHAOS TRIGGERED: #{redis_key} (TTL #{CHAOS_TTL_SECONDS}s) by user #{current_user_id}")

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

          # Resolve any open incidents for chaos-managed services so the next
          # demo run can create fresh incidents without hitting the dedup guard.
          resolved_incidents = []
          VALID_SCENARIOS.each_key do |svc|
            Incident.where(affected_service: svc)
                    .where(status: %w[open investigating])
                    .each do |incident|
              begin
                incident.resolve!
                resolved_incidents << incident.id
              rescue Incident::InvalidTransitionError => e
                Rails.logger.warn("CHAOS RESET: skipping incident #{incident.id}: #{e.message}")
              end
            end
          end

          Rails.logger.warn(
            "CHAOS RESET by user #{current_user_id}: cleared #{keys.size} flag(s): #{keys.join(', ')}; " \
            "resolved #{resolved_incidents.size} incident(s)"
          )

          render json: { status: 'reset', cleared: keys, resolved_incidents: resolved_incidents }
        end

        private

        def redis
          @redis ||= begin
            url = ServiceEnv.redis_url
            Redis.new(url: url, timeout: 2)
          end
        end

        # 403 (not 401) on a bad secret: the caller's JWT is valid, and the admin
        # dashboard treats 401 as "session expired" and logs the user out.
        def verify_chaos_secret
          expected = ENV.fetch('CHAOS_SECRET', '').to_s
          if expected.strip.empty?
            return render json: {
              error: 'Chaos injection is disabled: CHAOS_SECRET is not configured',
              code:  'chaos_disabled',
            }, status: :service_unavailable
          end

          provided = request.headers['X-Chaos-Secret'].to_s
          return if !provided.empty? && ActiveSupport::SecurityUtils.secure_compare(provided, expected)

          render json: { error: 'Invalid or missing X-Chaos-Secret header', code: 'chaos_secret_required' },
                 status: :forbidden
        end
      end
    end
  end
end
