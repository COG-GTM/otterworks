require 'rails_helper'

# Complements spec/models/admin_user_spec.rb with the status predicates.
RSpec.describe AdminUser do
  describe '#active?' do
    it 'is true only for an active user' do
      expect(build(:admin_user)).to be_active
      expect(build(:admin_user, :suspended)).not_to be_active
      expect(build(:admin_user, :deleted)).not_to be_active
    end
  end

  describe '#suspended?' do
    it 'is true only for a suspended user' do
      expect(build(:admin_user, :suspended)).to be_suspended
      expect(build(:admin_user)).not_to be_suspended
    end
  end

  describe 'the predicates after a transition' do
    it 'tracks suspend! and activate!' do
      user = create(:admin_user)

      user.suspend!(reason: 'spam')
      expect(user).to be_suspended
      expect(user).not_to be_active

      user.activate!
      expect(user).to be_active
      expect(user.suspended_reason).to be_nil
    end
  end
end
