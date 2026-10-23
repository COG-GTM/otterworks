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

        # JwtAuthenticator authenticates the caller; only admins may inject
        # failures or resolve incidents. CHAOS_SECRET, when configured, is an
        # additional factor for the same admins — never a replacement.
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

          # Start background probe to generate traffic → Prometheus metrics → Grafana alert.
          # At most one probe runs per key, so repeated triggers don't stack threads.
          ChaosProbeService.start(service: svc, redis_key: redis_key)

          Rails.logger.warn("CHAOS TRIGGERED: #{redis_key} (TTL #{CHAOS_TTL_SECONDS}s) by #{current_user_id}")
          AuditLogger.log(
            action: 'chaos.triggered',
            resource_type: 'ChaosFlag',
            request: request,
            changes_made: { key: redis_key, service: svc, scenario: scenario, ttl_seconds: CHAOS_TTL_SECONDS }
          )

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

          Rails.logger.warn("CHAOS RESET by #{current_user_id}: cleared #{keys.size} flag(s): #{keys.join(', ')}; " \
                            "resolved #{resolved_incidents.size} incident(s)")
          AuditLogger.log(
            action: 'chaos.reset',
            resource_type: 'ChaosFlag',
            request: request,
            changes_made: { cleared: keys, resolved_incidents: resolved_incidents }
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

        def verify_chaos_secret
          expected = ENV.fetch('CHAOS_SECRET', nil)
          return if expected.blank? # admin JWT alone (require_admin!) when no second factor is configured

          provided = request.headers['X-Chaos-Secret']
          return if ActiveSupport::SecurityUtils.secure_compare(provided.to_s, expected)

          render json: { error: 'Unauthorized' }, status: :unauthorized
        end
      end
    end
  end
end
