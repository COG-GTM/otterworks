require 'rails_helper'
require Rails.root.join('db/migrate/20240101000009_rename_system_configs_key_to_config_key')

RSpec.describe RenameSystemConfigsKeyToConfigKey do
  let(:connection) { ActiveRecord::Base.connection }

  after { SystemConfig.reset_column_information }

  def migrate_up
    ActiveRecord::Migration.suppress_messages { described_class.new.migrate(:up) }
    SystemConfig.reset_column_information
  end

  context 'when the table still has the legacy key column' do
    before do
      connection.rename_column :system_configs, :config_key, :key
      connection.execute(<<~SQL.squish)
        INSERT INTO system_configs (id, key, value, value_type, created_at, updated_at)
        VALUES (gen_random_uuid(), 'maintenance_mode', 'false', 'boolean', NOW(), NOW()),
               (gen_random_uuid(), 'session_timeout_minutes', '30', 'integer', NOW(), NOW())
      SQL
    end

    it 'renames key to config_key and keeps the existing values' do
      migrate_up

      expect(connection.column_exists?(:system_configs, :key)).to be false
      expect(SystemConfig.order(:config_key).pluck(:config_key, :value))
        .to eq([%w[maintenance_mode false], %w[session_timeout_minutes 30]])
    end

    it 'keeps config_key unique' do
      migrate_up

      expect(connection.index_exists?(:system_configs, :config_key,
                                      unique: true, name: 'index_system_configs_on_config_key')).to be true
      expect do
        connection.execute(<<~SQL.squish)
          INSERT INTO system_configs (id, config_key, value, value_type, created_at, updated_at)
          VALUES (gen_random_uuid(), 'maintenance_mode', 'true', 'boolean', NOW(), NOW())
        SQL
      end.to raise_error(ActiveRecord::RecordNotUnique)
    end
  end

  context 'when the table already has config_key' do
    it 'leaves the schema unchanged' do
      expect { migrate_up }.not_to(change { connection.columns(:system_configs).map(&:name).sort })
    end
  end
end
