require 'rails_helper'

RSpec.describe AuditLogger do
  describe '.log' do
    it 'records an audit log with explicit actor details' do
      expect do
        described_class.log(
          action: 'incident.created',
          resource_type: 'Incident',
          resource_id: SecureRandom.uuid,
          actor_id: SecureRandom.uuid,
          actor_email: 'admin@otterworks.com',
          changes_made: { status: 'open' }
        )
      end.to change(AuditLog, :count).by(1)

      expect(AuditLog.last).to have_attributes(
        action: 'incident.created',
        resource_type: 'Incident',
        actor_email: 'admin@otterworks.com',
        changes_made: { 'status' => 'open' }
      )
    end

    it 'derives the actor and client metadata from the request' do
      request = ActionDispatch::TestRequest.create(
        'jwt.user_id' => '11111111-1111-1111-1111-111111111111',
        'jwt.user_email' => 'from-jwt@otterworks.com',
        'HTTP_USER_AGENT' => 'RSpec Agent'
      )

      described_class.log(action: 'config.updated', resource_type: 'SystemConfig', request: request)

      expect(AuditLog.last).to have_attributes(
        actor_id: '11111111-1111-1111-1111-111111111111',
        actor_email: 'from-jwt@otterworks.com',
        user_agent: 'RSpec Agent',
        ip_address: request.remote_ip
      )
    end

    it 'swallows and logs persistence failures' do
      allow(AuditLog).to receive(:record!).and_raise(ActiveRecord::StatementInvalid, 'table gone')
      allow(Rails.logger).to receive(:error)

      expect { described_class.log(action: 'x', resource_type: 'Y') }.not_to raise_error
      expect(Rails.logger).to have_received(:error).with(/table gone/)
    end
  end
end
