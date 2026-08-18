require 'rails_helper'

RSpec.describe StorageQuotaPolicy do
  let(:quota) { build(:storage_quota) }

  def user_with_role(role)
    ApplicationController::RequestUser.new(id: SecureRandom.uuid, email: 'user@otterworks.com', roles: Array(role))
  end

  describe '#show?' do
    it 'permits admins and super_admins' do
      expect(described_class.new(user_with_role('admin'), quota).show?).to be(true)
      expect(described_class.new(user_with_role('super_admin'), quota).show?).to be(true)
    end

    it 'permits the uppercase ADMIN role from auth-service tokens' do
      expect(described_class.new(user_with_role('ADMIN'), quota).show?).to be(true)
    end

    it 'denies other roles' do
      expect(described_class.new(user_with_role('support'), quota).show?).to be(false)
      expect(described_class.new(nil, quota).show?).to be(false)
    end
  end

  describe '#update?' do
    it 'permits admins and super_admins' do
      expect(described_class.new(user_with_role('admin'), quota).update?).to be(true)
      expect(described_class.new(user_with_role('super_admin'), quota).update?).to be(true)
    end

    it 'denies other roles' do
      expect(described_class.new(user_with_role('viewer'), quota).update?).to be(false)
    end
  end
end
