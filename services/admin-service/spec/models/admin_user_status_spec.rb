require 'rails_helper'

RSpec.describe AdminUser do
  describe 'status predicates' do
    it 'reports an active user' do
      user = build(:admin_user, status: 'active')

      expect(user).to be_active
      expect(user).not_to be_suspended
    end

    it 'reports a suspended user' do
      user = build(:admin_user, :suspended)

      expect(user).to be_suspended
      expect(user).not_to be_active
    end

    it 'reports a soft-deleted user as neither active nor suspended' do
      user = build(:admin_user, :deleted)

      expect(user).not_to be_active
      expect(user).not_to be_suspended
    end
  end
end
