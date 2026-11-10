require 'rails_helper'
require 'aws-sdk-sns'

# OTW-69 (OTW-63 US5): policy changes are sent to audit-service over the shared SNS topic.
RSpec.describe AuditEventPublisher do
  let(:topic_arn) { 'arn:aws:sns:us-east-1:000000000000:otterworks-events' }
  let(:sns) { Aws::SNS::Client.new(stub_responses: true, region: 'us-east-1') }
  let(:old_policy) { { default_expiry_days: 30, min_expiry_days: 1, max_expiry_days: 90 } }
  let(:new_policy) { { default_expiry_days: 14, min_expiry_days: 7, max_expiry_days: 60 } }

  around do |example|
    previous = ENV.fetch('AUDIT_EVENTS_SNS_TOPIC_ARN', nil)
    ENV['AUDIT_EVENTS_SNS_TOPIC_ARN'] = topic_arn
    described_class.client = sns
    example.run
  ensure
    ENV['AUDIT_EVENTS_SNS_TOPIC_ARN'] = previous
    described_class.client = nil
  end

  def published_messages
    sns.api_requests.select { |r| r[:operation_name] == :publish }.map { |r| r[:params] }
  end

  it 'Given a policy change, Then publishes a schema-shaped policy_changed event in the document-service envelope' do
    at = Time.utc(2026, 11, 10, 17, 0, 0)
    actor = SecureRandom.uuid

    expect(described_class.publish_policy_changed(workspace_id: 'default', actor_id: actor,
                                                  old_value: old_policy, new_value: new_policy, at: at)).to be(true)

    request = published_messages.sole
    expect(request[:topic_arn]).to eq(topic_arn)
    expect(request[:message_attributes]['event_type'][:string_value]).to eq('folder_share_link.policy_changed')
    message = JSON.parse(request[:message])
    expect(message['event_type']).to eq('folder_share_link.policy_changed')
    payload = message['payload']
    expect(payload).to include(
      'eventType' => 'folder_share_link.policy_changed',
      'actor' => { 'type' => 'user', 'id' => actor },
      'workspaceId' => 'default',
      'resource' => { 'type' => 'sharing_policy', 'workspaceId' => 'default' },
      'oldValue' => old_policy.stringify_keys,
      'newValue' => new_policy.stringify_keys,
      'timestamp' => '2026-11-10T17:00:00.000000Z'
    )
    expect(payload['auditId']).to match(/\A\h{8}-\h{4}-\h{4}-\h{4}-\h{12}\z/)
  end

  it 'Given no topic is configured, Then skips publishing' do
    ENV['AUDIT_EVENTS_SNS_TOPIC_ARN'] = ''

    expect(described_class.publish('folder_share_link.policy_changed', {})).to be(false)
    expect(published_messages).to be_empty
  end

  it 'Given SNS fails, Then returns false without raising' do
    sns.stub_responses(:publish, 'InternalError')

    expect(described_class.publish('folder_share_link.policy_changed', {})).to be(false)
  end
end
