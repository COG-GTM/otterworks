class Announcement < ApplicationRecord
  SEVERITIES = %w[info warning critical maintenance].freeze
  STATUSES = %w[draft published archived].freeze

  validates :title, presence: true, length: { maximum: 255 }
  validates :body, presence: true
  validates :severity, presence: true, inclusion: { in: SEVERITIES }
  validates :status, presence: true, inclusion: { in: STATUSES }
  validate :ends_at_after_starts_at, if: -> { starts_at.present? && ends_at.present? }

  scope :published, -> { where(status: 'published') }
  scope :active, lambda {
    published.where('starts_at IS NULL OR starts_at <= ?', Time.current)
             .where('ends_at IS NULL OR ends_at >= ?', Time.current)
  }
  scope :by_severity, ->(severity) { where(severity: severity) }
  # target_audience is either { "role" => "all" | "admins" | "editors" | "viewers" } (admin dashboard)
  # or { "roles" => [...] } (seed data); a missing/empty audience means everyone.
  scope :for_role, lambda { |role|
    role = role.to_s.downcase
    audiences = ['all', role, role.pluralize].uniq
    where("COALESCE(target_audience->>'role', 'all') IN (?)", audiences)
      .where("CASE WHEN jsonb_typeof(target_audience->'roles') = 'array' " \
             "AND jsonb_array_length(target_audience->'roles') > 0 " \
             "THEN jsonb_exists_any(target_audience->'roles', ARRAY[?]::text[]) ELSE TRUE END", audiences)
  }

  def publish!
    update!(status: 'published')
  end

  def archive!
    update!(status: 'archived')
  end

  def active?
    status == 'published' &&
      (starts_at.nil? || starts_at <= Time.current) &&
      (ends_at.nil? || ends_at >= Time.current)
  end

  private

  def ends_at_after_starts_at
    errors.add(:ends_at, 'must be after starts_at') if ends_at <= starts_at
  end
end
