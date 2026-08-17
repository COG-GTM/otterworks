require 'rails_helper'

RSpec.describe AuditLogger do
  let(:actor_id) { SecureRandom.uuid }

  describe '.log' do
    it 'records an audit entry with explicit actor details' do
      expect do
        described_class.log(action: 'config.updated', resource_type: 'SystemConfig', resource_id: 'abc',
                            actor_id: actor_id, actor_email: 'admin@otterworks.com',
                            changes_made: { before: '1', after: '2' })
      end.to change(AuditLog, :count).by(1)

      log = AuditLog.last
      expect(log.action).to eq('config.updated')
      expect(log.actor_id).to eq(actor_id)
      expect(log.actor_email).to eq('admin@otterworks.com')
      expect(log.changes_made).to include('before' => '1', 'after' => '2')
    end

    it 'derives the actor and client metadata from the request' do
      request = ActionDispatch::TestRequest.create
      request.env['jwt.user_id'] = actor_id
      request.env['jwt.user_email'] = 'ops@otterworks.com'
      request.env['HTTP_USER_AGENT'] = 'rspec-agent'

      described_class.log(action: 'incident.created', resource_type: 'Incident', request: request)

      log = AuditLog.last
      expect(log.actor_id).to eq(actor_id)
      expect(log.actor_email).to eq('ops@otterworks.com')
      expect(log.user_agent).to eq('rspec-agent')
      expect(log.ip_address).to be_present
    end

    it 'swallows and logs persistence failures' do
      allow(AuditLog).to receive(:record!).and_raise(ActiveRecord::StatementInvalid, 'table gone')
      allow(Rails.logger).to receive(:error)

      expect { described_class.log(action: 'x', resource_type: 'Y') }.not_to raise_error
      expect(Rails.logger).to have_received(:error).with(/table gone/)
    end
  end
end
