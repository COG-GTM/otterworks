# Databases created before 20240101000003 was changed still have the
# reserved-word column `key`; fresh databases already get `config_key`.
class RenameSystemConfigsKeyToConfigKey < ActiveRecord::Migration[7.1]
  def up
    return unless column_exists?(:system_configs, :key)

    rename_column :system_configs, :key, :config_key
  end

  def down
    # No-op: 20240101000003 creates `config_key`, so there is nothing to restore.
  end
end
