class CreateSharingPolicies < ActiveRecord::Migration[7.1]
  def change
    create_table :sharing_policies, id: :uuid do |t|
      t.string :workspace_id, null: false, default: "default"
      t.integer :default_expiry_days, null: false, default: 30
      t.integer :min_expiry_days, null: false, default: 1
      t.integer :max_expiry_days, null: false, default: 90
      t.uuid :updated_by
      t.timestamps
    end

    add_index :sharing_policies, :workspace_id, unique: true
    add_check_constraint :sharing_policies,
                         "min_expiry_days >= 1 AND max_expiry_days <= 90 AND min_expiry_days <= max_expiry_days " \
                         "AND default_expiry_days BETWEEN min_expiry_days AND max_expiry_days",
                         name: "sharing_policies_expiry_bounds"
  end
end
