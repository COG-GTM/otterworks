# Org-wide folder share-link expiry policy. There is no workspace entity yet, so a
# single row keyed by workspace_id 'default' holds the policy.
class SharingPolicy < ApplicationRecord
  DEFAULT_WORKSPACE_ID = 'default'.freeze
  DEFAULT_EXPIRY_DAYS = 30
  MIN_EXPIRY_DAYS = 1
  MAX_EXPIRY_DAYS = 90
  POLICY_FIELDS = %w[default_expiry_days min_expiry_days max_expiry_days].freeze

  validates :workspace_id, presence: true, uniqueness: true
  validates :default_expiry_days, numericality: { only_integer: true }
  validates :min_expiry_days, numericality: { only_integer: true, greater_than_or_equal_to: MIN_EXPIRY_DAYS }
  validates :max_expiry_days, numericality: { only_integer: true, less_than_or_equal_to: MAX_EXPIRY_DAYS }
  validate :bounds_in_order
  validate :default_within_bounds

  def self.for_workspace(workspace_id = DEFAULT_WORKSPACE_ID)
    find_by(workspace_id: workspace_id) || new(
      workspace_id: workspace_id,
      default_expiry_days: DEFAULT_EXPIRY_DAYS,
      min_expiry_days: MIN_EXPIRY_DAYS,
      max_expiry_days: MAX_EXPIRY_DAYS
    )
  end

  def to_policy
    {
      default_expiry_days: default_expiry_days,
      min_expiry_days: min_expiry_days,
      max_expiry_days: max_expiry_days
    }
  end

  private

  def integer_fields?
    POLICY_FIELDS.all? { |field| errors[field].empty? && public_send(field).is_a?(Integer) }
  end

  def bounds_in_order
    return unless integer_fields?
    return if min_expiry_days <= max_expiry_days

    errors.add(:min_expiry_days, 'must be less than or equal to max_expiry_days')
  end

  def default_within_bounds
    return unless integer_fields?
    return if default_expiry_days.between?(min_expiry_days, max_expiry_days)

    errors.add(:default_expiry_days, 'must be between min_expiry_days and max_expiry_days')
  end
end
