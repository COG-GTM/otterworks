require 'rails_helper'

RSpec.describe AlertBudget do
  def with_env(vars)
    previous = vars.keys.index_with { |k| ENV.fetch(k, nil) }
    vars.each { |k, v| v.nil? ? ENV.delete(k) : ENV[k] = v }
    yield
  ensure
    previous.each { |k, v| v.nil? ? ENV.delete(k) : ENV[k] = v }
  end

  describe '.reserve_devin_session' do
    it 'grants slots up to the per-service limit' do
      with_env('ALERT_MAX_DEVIN_SESSIONS_PER_SERVICE' => '2') do
        expect(described_class.reserve_devin_session('file-service')).to be(true)
        expect(described_class.reserve_devin_session('file-service')).to be(true)
        expect(described_class.reserve_devin_session('file-service')).to be(false)
        expect(described_class.reserve_devin_session('search-service')).to be(true)
      end
    end

    it 'is independent of the incident budget' do
      with_env('ALERT_MAX_DEVIN_SESSIONS_PER_SERVICE' => '1', 'ALERT_MAX_INCIDENTS_PER_SERVICE' => '1') do
        expect(described_class.reserve_incident('file-service')).to be(true)
        expect(described_class.reserve_devin_session('file-service')).to be(true)
        expect(described_class.reserve_incident('file-service')).to be(false)
      end
    end

    it 'frees slots once reservations leave the window and prunes them' do
      with_env('ALERT_MAX_DEVIN_SESSIONS_PER_SERVICE' => '1') do
        AlertBudgetReservation.create!(kind: 'devin_session', affected_service: 'file-service',
                                       created_at: 2.hours.ago)

        expect(described_class.reserve_devin_session('file-service')).to be(true)
        expect(AlertBudgetReservation.where(kind: 'devin_session').count).to eq(1)
      end
    end

    it 'takes a per-service advisory lock before counting' do
      allow(AlertBudgetReservation.connection).to receive(:execute).and_call_original

      described_class.reserve_devin_session('file-service')

      expect(AlertBudgetReservation.connection).to have_received(:execute)
        .with(a_string_including('pg_advisory_xact_lock', 'alert_budget:devin_session:file-service'))
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
