require 'rails_helper'

RSpec.describe BulkOperationsService do
  describe '.process' do
    it 'records a per-user error when an operation fails' do
      good = create(:admin_user)
      bad = create(:admin_user)

      result = described_class.process(operation: 'update_role', user_ids: [good.id, bad.id],
                                       params: { role: 'wizard' })

      expect(result.success_count).to eq(0)
      expect(result.failure_count).to eq(2)
      expect(result.errors.map { |e| e[:user_id] }).to contain_exactly(good.id, bad.id)
      expect(result.errors.first[:error]).to match(/Role is not included in the list/)
      expect(good.reload.role).to eq('viewer')
    end

    it 'mixes successes and failures across the batch' do
      users = create_list(:admin_user, 2)
      result = described_class.process(operation: 'suspend', user_ids: users.map(&:id) + [SecureRandom.uuid],
                                       params: { reason: 'abuse' })

      expect(result.success_count).to eq(2)
      expect(result.failure_count).to eq(1)
      expect(result.errors.last[:error]).to eq('1 user(s) not found')
      expect(users.map { |u| u.reload.suspended_reason }.uniq).to eq(['abuse'])
    end
  end
end
