require 'rails_helper'

RSpec.describe AuditLogger do
  let(:actor_id) { SecureRandom.uuid }
  let(:resource_id) { SecureRandom.uuid }

  describe '.log' do
    it 'records an audit entry with explicit actor details' do
      expect do
        described_class.log(action: 'user.updated', resource_type: 'AdminUser', resource_id: resource_id,
                            actor_id: actor_id, actor_email: 'admin@otterworks.com',
                            changes_made: { role: 'editor' })
      end.to change(AuditLog, :count).by(1)

      log = AuditLog.last
      expect(log.actor_id).to eq(actor_id)
      expect(log.resource_id).to eq(resource_id)
      expect(log.actor_email).to eq('admin@otterworks.com')
      expect(log.changes_made).to eq('role' => 'editor')
    end

    it 'derives the actor from the request JWT env' do
      request = instance_double(ActionDispatch::Request,
                                env: { 'jwt.user_id' => actor_id, 'jwt.user_email' => 'jwt@otterworks.com' },
                                remote_ip: '10.0.0.1', user_agent: 'RSpec')

      described_class.log(action: 'config.updated', resource_type: 'SystemConfig', request: request)

      log = AuditLog.last
      expect(log.actor_id).to eq(actor_id)
      expect(log.actor_email).to eq('jwt@otterworks.com')
      expect(log.ip_address).to eq('10.0.0.1')
      expect(log.user_agent).to eq('RSpec')
    end

    it 'swallows and logs persistence failures' do
      allow(AuditLog).to receive(:record!).and_raise(ActiveRecord::RecordInvalid)
      allow(Rails.logger).to receive(:error)

      expect { described_class.log(action: 'x', resource_type: 'Y') }.not_to raise_error
      expect(Rails.logger).to have_received(:error).with(/Failed to record audit log/)
    end
  end
end
