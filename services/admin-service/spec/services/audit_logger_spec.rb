require 'rails_helper'

RSpec.describe AuditLogger do
  let(:actor_id) { SecureRandom.uuid }
  let(:resource_id) { SecureRandom.uuid }

  describe '.log' do
    it 'records the audit entry, defaulting the actor to the JWT env of the request' do
      request = instance_double(
        ActionDispatch::Request,
        env: { 'jwt.user_id' => actor_id, 'jwt.user_email' => 'admin@otterworks.com' },
        remote_ip: '10.0.0.9',
        user_agent: 'rspec'
      )

      expect do
        described_class.log(action: 'thing.created', resource_type: 'Thing', resource_id: resource_id,
                            request: request, changes_made: { a: 1 })
      end.to change(AuditLog, :count).by(1)

      log = AuditLog.last
      expect(log).to have_attributes(action: 'thing.created', resource_type: 'Thing', resource_id: resource_id,
                                     actor_id: actor_id, actor_email: 'admin@otterworks.com',
                                     ip_address: '10.0.0.9', user_agent: 'rspec')
      expect(log.changes_made).to eq('a' => 1)
    end

    it 'prefers explicitly supplied actor details over the request' do
      described_class.log(action: 'thing.created', resource_type: 'Thing',
                          actor_id: actor_id, actor_email: 'system@otterworks.com')

      expect(AuditLog.last).to have_attributes(actor_id: actor_id, actor_email: 'system@otterworks.com')
    end

    it 'swallows and logs persistence failures' do
      allow(Rails.logger).to receive(:error)
      allow(AuditLog).to receive(:record!).and_raise(ActiveRecord::StatementInvalid, 'table missing')

      expect do
        described_class.log(action: 'thing.created', resource_type: 'Thing')
      end.not_to raise_error

      expect(Rails.logger).to have_received(:error).with('Failed to record audit log: table missing')
    end
  end
end
