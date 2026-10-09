class CreateAlertBudgetReservations < ActiveRecord::Migration[7.1]
  def change
    create_table :alert_budget_reservations, id: :uuid do |t|
      t.string :kind, null: false
      t.string :affected_service, null: false
      t.datetime :created_at, null: false
    end
    add_index :alert_budget_reservations, %i[kind affected_service created_at],
              name: 'index_alert_budget_reservations_on_kind_service_created'
  end
end
