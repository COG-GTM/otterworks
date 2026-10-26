class AddSourceToIncidents < ActiveRecord::Migration[7.1]
  ALERT_MARKER = '**Source**: Grafana Unified Alerting (auto-generated incident)'.freeze

  def up
    add_column :incidents, :source, :string, null: false, default: 'manual'
    add_index :incidents, %i[source affected_service created_at], name: 'index_incidents_on_source_service_created_at'

    # Incidents opened by the alert webhook before this column existed carry
    # no reporter and end with the webhook's source line.
    execute <<~SQL.squish
      UPDATE incidents SET source = 'alert'
      WHERE reporter_id IS NULL
        AND description LIKE #{connection.quote("%#{ALERT_MARKER}")}
    SQL
  end

  def down
    remove_index :incidents, name: 'index_incidents_on_source_service_created_at'
    remove_column :incidents, :source
  end
end
