class AlertBudgetReservation < ApplicationRecord
  KINDS = %w[incident devin_session].freeze

  validates :kind, inclusion: { in: KINDS }
  validates :affected_service, presence: true
end
