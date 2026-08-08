require 'rails_helper'

# Complements spec/models/admin_user_spec.rb by covering the status predicates.
RSpec.describe AdminUser do
  describe '#active?' do
    it 'is true only for the active status' do
      expect(build(:admin_user)).to be_active
      expect(build(:admin_user, :suspended)).not_to be_active
      expect(build(:admin_user, :deleted)).not_to be_active
    end
  end

  describe '#suspended?' do
    it 'is true only for the suspended status' do
      expect(build(:admin_user, :suspended)).to be_suspended
      expect(build(:admin_user)).not_to be_suspended
    end
  end
end
