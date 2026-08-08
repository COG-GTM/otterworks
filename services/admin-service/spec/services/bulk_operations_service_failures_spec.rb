require 'rails_helper'

# Complements spec/services/bulk_operations_service_spec.rb with the per-user failure path.
RSpec.describe BulkOperationsService do
  describe '.process' do
    it 'counts and reports a user whose update is rejected' do
      good = create(:admin_user, role: 'viewer')
      bad = create(:admin_user, role: 'viewer')

      result = described_class.process(operation: 'update_role', user_ids: [good.id, bad.id],
                                       params: { role: 'wizard' })

      expect(result.success_count).to eq(0)
      expect(result.failure_count).to eq(2)
      expect(result.errors.map { |e| e[:user_id] }).to contain_exactly(good.id, bad.id)
      expect(result.errors.first[:error]).to match(/Role is not included in the list/)
    end

    it 'mixes successes and failures' do
      ok = create(:admin_user)
      broken = create(:admin_user, role: 'viewer')
      broken.update_column(:email, 'not-an-email')

      result = described_class.process(operation: 'update_role', user_ids: [ok.id, broken.id],
                                       params: { role: 'admin' })

      expect(result.success_count).to eq(1)
      expect(result.failure_count).to eq(1)
      expect(result.errors.first).to include(user_id: broken.id)
      expect(ok.reload.role).to eq('admin')
    end
  end
end
