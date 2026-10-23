require 'rails_helper'

RSpec.describe 'config/database.yml' do # rubocop:disable RSpec/DescribeClass
  let(:path) { Rails.root.join('config/database.yml') }

  def with_env(vars)
    previous = vars.keys.to_h { |k| [k, ENV.fetch(k, nil)] }
    vars.each { |k, v| v.nil? ? ENV.delete(k) : ENV[k] = v }
    yield
  ensure
    previous.each { |k, v| v.nil? ? ENV.delete(k) : ENV[k] = v }
  end

  def load_config(rails_env)
    allow(Rails).to receive(:env).and_return(ActiveSupport::EnvironmentInquirer.new(rails_env))
    ActiveSupport::ConfigurationFile.parse(path)
  end

  context 'when DATABASE_PASSWORD is unset' do
    it 'refuses to load in production instead of using a default password' do
      with_env('DATABASE_PASSWORD' => nil) do
        expect { load_config('production') }.to raise_error(KeyError, /DATABASE_PASSWORD must be set in production/)
      end
    end

    it 'keeps the local default password for development and test' do
      with_env('DATABASE_PASSWORD' => nil) do
        config = load_config('test')
        expect(config.dig('development', 'password')).to eq('otterworks')
        expect(config.dig('test', 'password')).to eq('otterworks')
        expect(config.dig('production', 'password')).to be_nil
      end
    end
  end

  it 'uses DATABASE_PASSWORD in production when it is set' do
    with_env('DATABASE_PASSWORD' => 'from-secret') do
      production = load_config('production')['production']
      expect(production['password']).to eq('from-secret')
      expect(production['database']).to eq(ENV.fetch('DATABASE_NAME', 'otterworks_coggtm'))
    end
  end
end
