require 'rails_helper'

# Complements spec/services/bulk_operations_service_spec.rb by covering the
# per-user rescue branch.
RSpec.describe BulkOperationsService do
  describe '.process with a failing record' do
    it 'counts the failure and reports the record error' do
      user = create(:admin_user)

      result = described_class.process(operation: 'update_role', user_ids: [user.id], params: { role: 'wizard' })

      expect(result.success_count).to eq(0)
      expect(result.failure_count).to eq(1)
      expect(result.errors.first[:user_id]).to eq(user.id)
      expect(result.errors.first[:error]).to match(/Role is not included in the list/)
      expect(user.reload.role).to eq('viewer')
    end
  end
end
