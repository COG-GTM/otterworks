require 'rails_helper'

RSpec.describe AdminUser do
  describe '#active?' do
    it 'is true only while the status is active' do
      expect(build(:admin_user, status: 'active')).to be_active
      expect(build(:admin_user, :suspended)).not_to be_active
      expect(build(:admin_user, :deleted)).not_to be_active
    end
  end

  describe '#suspended?' do
    it 'is true only while the status is suspended' do
      expect(build(:admin_user, :suspended)).to be_suspended
      expect(build(:admin_user, status: 'active')).not_to be_suspended
    end
  end
end
