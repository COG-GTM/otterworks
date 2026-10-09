require 'rails_helper'

RSpec.describe AlertBudget do
  def incident(service: 'file-service', session_id: nil, created_at: Time.current)
    Incident.create!(title: 't', description: 'd', severity: 'high', status: 'open',
                     affected_service: service, devin_session_id: session_id, created_at: created_at)
  end

  def with_env(vars)
    previous = vars.keys.index_with { |k| ENV.fetch(k, nil) }
    vars.each { |k, v| v.nil? ? ENV.delete(k) : ENV[k] = v }
    yield
  ensure
    previous.each { |k, v| v.nil? ? ENV.delete(k) : ENV[k] = v }
  end

  describe '.devin_session_allowed?' do
    it 'counts only recent incidents with a Devin session for that service' do
      with_env('ALERT_MAX_DEVIN_SESSIONS_PER_SERVICE' => '2') do
        incident(session_id: 's1')
        incident(session_id: nil)
        incident(service: 'search-service', session_id: 's2')
        incident(session_id: 's3', created_at: 2.hours.ago)
        expect(described_class.devin_session_allowed?('file-service')).to be(true)

        incident(session_id: 's4')
        expect(described_class.devin_session_allowed?('file-service')).to be(false)
        expect(described_class.devin_session_allowed?('search-service')).to be(true)
      end
    end
  end

  describe '.dedup_bypass_allowed?' do
    it 'caps recent incidents per service' do
      with_env('ALERT_MAX_INCIDENTS_PER_SERVICE' => '1') do
        expect(described_class.dedup_bypass_allowed?('file-service')).to be(true)
        incident
        expect(described_class.dedup_bypass_allowed?('file-service')).to be(false)
      end
    end
  end

  describe 'configuration' do
    it 'falls back to defaults for missing or invalid values' do
      with_env('ALERT_MAX_DEVIN_SESSIONS_PER_SERVICE' => 'abc', 'ALERT_MAX_INCIDENTS_PER_SERVICE' => '0',
               'ALERT_BUDGET_WINDOW_SECONDS' => nil) do
        expect(described_class.max_devin_sessions_per_service).to eq(described_class::DEFAULT_MAX_DEVIN_SESSIONS_PER_SERVICE)
        expect(described_class.max_incidents_per_service).to eq(described_class::DEFAULT_MAX_INCIDENTS_PER_SERVICE)
        expect(described_class.window_seconds).to eq(described_class::DEFAULT_WINDOW_SECONDS)
      end
    end
  end
end
