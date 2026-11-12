require 'rails_helper'

RSpec.describe AuditLog do
  describe 'validations' do
    it { is_expected.to validate_presence_of(:action) }
    it { is_expected.to validate_presence_of(:resource_type) }
  end

  describe 'scopes' do
    let!(:recent_log) { create(:audit_log, created_at: 1.hour.ago) }
    let!(:old_log) { create(:audit_log, created_at: 2.days.ago) }

    describe '.recent' do
      it 'orders by created_at descending' do
        expect(described_class.recent.first).to eq(recent_log)
      end
    end

    describe '.since' do
      it 'returns logs since the given time' do
        expect(described_class.since(1.day.ago)).to include(recent_log)
        expect(described_class.since(1.day.ago)).not_to include(old_log)
      end
    end

    describe '.by_action' do
      it 'filters by action' do
        expect(described_class.by_action('user.updated')).to include(recent_log)
      end
    end
  end

  describe '.record!' do
    it 'creates an audit log entry' do
      expect do
        described_class.record!(
          action: 'user.created',
          resource_type: 'AdminUser',
          resource_id: SecureRandom.uuid,
          actor_email: 'admin@test.com'
        )
      end.to change(described_class, :count).by(1)
    end

    it 'persists every supported attribute' do
      resource_id = SecureRandom.uuid
      actor_id = SecureRandom.uuid
      log = described_class.record!(
        action: 'user.updated',
        resource_type: 'AdminUser',
        resource_id: resource_id,
        actor_id: actor_id,
        actor_email: 'admin@test.com',
        changes_made: { 'role' => %w[viewer admin] },
        ip_address: '10.0.0.1',
        user_agent: 'rspec'
      )

      expect(log.reload).to have_attributes(
        action: 'user.updated', resource_type: 'AdminUser', resource_id: resource_id, actor_id: actor_id,
        actor_email: 'admin@test.com', changes_made: { 'role' => %w[viewer admin] },
        ip_address: '10.0.0.1', user_agent: 'rspec'
      )
    end

    it 'defaults changes_made to an empty hash' do
      log = described_class.record!(action: 'config.updated', resource_type: 'SystemConfig')

      expect(log.reload.changes_made).to eq({})
    end

    it 'rejects unknown attributes' do
      expect do
        described_class.record!(action: 'user.created', resource_type: 'AdminUser', role: 'admin')
      end.to raise_error(ArgumentError, /role/)
    end
  end
end
