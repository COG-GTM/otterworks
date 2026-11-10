require 'rails_helper'

RSpec.describe SharingPolicy do
  describe 'validations' do
    subject { build(:sharing_policy) }

    it { is_expected.to validate_uniqueness_of(:workspace_id) }
    it { is_expected.to be_valid }

    it 'rejects a minimum below 1 day' do
      expect(build(:sharing_policy, min_expiry_days: 0)).not_to be_valid
    end

    it 'rejects a maximum above 90 days' do
      expect(build(:sharing_policy, max_expiry_days: 91)).not_to be_valid
    end

    it 'rejects a minimum greater than the maximum' do
      policy = build(:sharing_policy, min_expiry_days: 20, max_expiry_days: 10, default_expiry_days: 15)
      expect(policy).not_to be_valid
      expect(policy.errors[:min_expiry_days]).to include('must be less than or equal to max_expiry_days')
    end

    it 'rejects a default outside [min, max]' do
      policy = build(:sharing_policy, min_expiry_days: 5, max_expiry_days: 10, default_expiry_days: 30)
      expect(policy).not_to be_valid
      expect(policy.errors[:default_expiry_days]).to include('must be between min_expiry_days and max_expiry_days')
    end

    it 'rejects non-integer values' do
      expect(build(:sharing_policy, default_expiry_days: 'abc')).not_to be_valid
      expect(build(:sharing_policy, default_expiry_days: 1.5)).not_to be_valid
    end

    it 'is also enforced by a database check constraint' do
      policy = create(:sharing_policy)
      expect { policy.update_columns(max_expiry_days: 120) }.to raise_error(ActiveRecord::StatementInvalid)
    end
  end

  describe '.for_workspace' do
    it 'returns the 30/1/90 defaults when no policy is stored' do
      policy = described_class.for_workspace
      expect(policy).to be_new_record
      expect(policy.to_policy).to eq(default_expiry_days: 30, min_expiry_days: 1, max_expiry_days: 90)
    end

    it 'returns the stored policy when one exists' do
      create(:sharing_policy, default_expiry_days: 14)
      expect(described_class.for_workspace.default_expiry_days).to eq(14)
    end
  end
end
