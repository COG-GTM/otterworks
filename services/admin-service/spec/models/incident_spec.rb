require 'rails_helper'

RSpec.describe Incident do
  include ActiveSupport::Testing::TimeHelpers

  describe 'validations' do
    subject { build(:incident) }

    it { is_expected.to validate_presence_of(:title) }
    it { is_expected.to validate_length_of(:title).is_at_most(255) }
    it { is_expected.to validate_presence_of(:description) }
    it { is_expected.to validate_inclusion_of(:severity).in_array(Incident::SEVERITIES) }
    it { is_expected.to validate_inclusion_of(:status).in_array(Incident::STATUSES) }

    it 'allows a blank affected_service' do
      expect(build(:incident, affected_service: nil)).to be_valid
    end

    it 'rejects an unknown affected_service' do
      expect(build(:incident, affected_service: 'mystery-service')).not_to be_valid
    end
  end

  describe 'scopes' do
    let!(:open_incident) { create(:incident, severity: 'low') }
    let!(:investigating) { create(:incident, :investigating, severity: 'critical') }
    let!(:resolved) { create(:incident, :resolved) }

    it 'filters by status' do
      expect(described_class.by_status('resolved')).to contain_exactly(resolved)
    end

    it 'filters by severity' do
      expect(described_class.by_severity('critical')).to contain_exactly(investigating)
    end

    it 'returns open and investigating incidents as active' do
      expect(described_class.active).to contain_exactly(open_incident, investigating)
    end
  end

  describe '#can_transition_to?' do
    {
      'open' => { allowed: %w[investigating resolved], denied: %w[open closed] },
      'investigating' => { allowed: %w[resolved], denied: %w[open investigating closed] },
      'resolved' => { allowed: %w[closed], denied: %w[open investigating resolved] },
      'closed' => { allowed: [], denied: %w[open investigating resolved closed] }
    }.each do |from, rules|
      rules[:allowed].each do |to|
        it "allows #{from} -> #{to}" do
          expect(build(:incident, status: from).can_transition_to?(to)).to be true
        end
      end

      rules[:denied].each do |to|
        it "denies #{from} -> #{to}" do
          expect(build(:incident, status: from).can_transition_to?(to)).to be false
        end
      end
    end

    it 'denies transitions from an unknown status' do
      expect(build(:incident, status: 'bogus').can_transition_to?('resolved')).to be false
    end
  end

  describe 'state transitions' do
    it 'moves open -> investigating' do
      incident = create(:incident)
      incident.investigate!
      expect(incident.reload.status).to eq('investigating')
    end

    it 'resolves and stamps resolved_at' do
      incident = create(:incident, :investigating)
      freeze_time do
        incident.resolve!
        expect(incident.reload.status).to eq('resolved')
        expect(incident.resolved_at).to eq(Time.current)
      end
    end

    it 'closes a resolved incident and stamps closed_at' do
      incident = create(:incident, :resolved)
      freeze_time do
        incident.close!
        expect(incident.reload.status).to eq('closed')
        expect(incident.closed_at).to eq(Time.current)
      end
    end

    it 'raises InvalidTransitionError on an illegal transition and leaves the record unchanged' do
      incident = create(:incident)
      expect { incident.close! }
        .to raise_error(Incident::InvalidTransitionError, "Cannot transition from 'open' to 'closed'")
      expect(incident.reload.status).to eq('open')
      expect(incident.closed_at).to be_nil
    end

    it 'cannot re-open investigation once resolved' do
      incident = create(:incident, :resolved)
      expect { incident.investigate! }.to raise_error(Incident::InvalidTransitionError)
    end
  end

  describe '#active?' do
    it 'is true for open and investigating' do
      expect(build(:incident).active?).to be true
      expect(build(:incident, :investigating).active?).to be true
    end

    it 'is false for resolved and closed' do
      expect(build(:incident, :resolved).active?).to be false
      expect(build(:incident, :closed).active?).to be false
    end
  end

  describe 'Devin session predicates' do
    it 'reports no session when devin_session_id is blank' do
      incident = build(:incident)
      expect(incident.has_devin_session?).to be false
      expect(incident.has_active_devin_session?).to be false
    end

    it 'reports an active session only while it is running' do
      incident = build(:incident, :with_session)
      expect(incident.has_devin_session?).to be true
      expect(incident.has_active_devin_session?).to be true

      incident.devin_session_status = 'finished'
      expect(incident.has_devin_session?).to be true
      expect(incident.has_active_devin_session?).to be false
    end
  end
end
