# Publishes audit events (shared/events/schemas/audit-events.json) to the domain SNS topic
# that audit-service's SQS queue is subscribed to. Uses the same envelope as document-service:
# { event_type, timestamp, payload }. Disabled when AUDIT_EVENTS_SNS_TOPIC_ARN is unset, and
# never raises: the local AuditLog row remains the record if delivery fails.
class AuditEventPublisher
  POLICY_CHANGED = 'folder_share_link.policy_changed'.freeze

  class << self
    attr_writer :client

    def publish_policy_changed(workspace_id:, actor_id:, old_value:, new_value:, at: Time.current)
      publish(POLICY_CHANGED, {
                eventType: POLICY_CHANGED,
                auditId: SecureRandom.uuid,
                actor: actor_id.present? ? { type: 'user', id: actor_id } : { type: 'system', id: nil },
                workspaceId: workspace_id,
                resource: { type: 'sharing_policy', workspaceId: workspace_id },
                oldValue: old_value,
                newValue: new_value,
                timestamp: at.utc.iso8601(6)
              })
    end

    def publish(event_type, payload)
      topic_arn = ENV.fetch('AUDIT_EVENTS_SNS_TOPIC_ARN', '')
      if topic_arn.empty?
        Rails.logger.info("audit_event_skipped event_type=#{event_type}")
        return false
      end

      message = { event_type: event_type, timestamp: Time.current.utc.iso8601(6), payload: payload }
      client.publish(
        topic_arn: topic_arn,
        message: message.to_json,
        message_attributes: { 'event_type' => { data_type: 'String', string_value: event_type } }
      )
      true
    rescue StandardError => e
      Rails.logger.error("audit_event_publish_failed event_type=#{event_type} error=#{e.class}: #{e.message}")
      false
    end

    def client
      @client ||= begin
        require 'aws-sdk-sns'
        options = { region: ENV.fetch('AWS_REGION', 'us-east-1') }
        endpoint = ENV.fetch('AWS_ENDPOINT_URL', '')
        options[:endpoint] = endpoint unless endpoint.empty?
        Aws::SNS::Client.new(**options)
      end
    end
  end
end
