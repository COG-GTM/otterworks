class ApplicationPolicy
  attr_reader :user, :record

  def initialize(user, record)
    @user = user
    @record = record
  end

  # Auth-service issues a `roles` claim with uppercase enum names (e.g.
  # ADMIN); compare case-insensitively.
  def admin?
    Array(user&.roles).map { |r| r.to_s.downcase }.intersect?(%w[admin super_admin])
  end
end
