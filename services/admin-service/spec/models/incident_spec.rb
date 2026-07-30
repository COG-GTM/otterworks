require 'rails_helper'

RSpec.describe Incident do
  describe 'validations' do
    subject { build(:incident) }

    it { is_expected.to validate_presence_of(:title) }
    it { is_expected.to validate_length_of(:title).is_at_most(255) }
    it { is_expected.to validate_presence_of(:description) }
    it { is_expected.to validate_presence_of(:severity) }
    it { is_expected.to validate_inclusion_of(:severity).in_array(described_class::SEVERITIES) }
    it { is_expected.to validate_presence_of(:status) }
    it { is_expected.to validate_inclusion_of(:status).in_array(described_class::STATUSES) }

    it 'allows a blank affected_service' do
      expect(build(:incident, affected_service: nil)).to be_valid
    end

    it 'rejects an unknown affected_service' do
      expect(build(:incident, affected_service: 'nope-service')).not_to be_valid
    end
  end

  describe 'scopes' do
    let!(:open_incident) { create(:incident, status: 'open', severity: 'low') }
    let!(:investigating) { create(:incident, :investigating, severity: 'critical') }
    let!(:resolved) { create(:incident, :resolved, severity: 'low') }

    it 'filters by status' do
      expect(described_class.by_status('resolved')).to contain_exactly(resolved)
    end

    it 'filters by severity' do
      expect(described_class.by_severity('critical')).to contain_exactly(investigating)
    end

    it 'returns only open and investigating incidents as active' do
      expect(described_class.active).to contain_exactly(open_incident, investigating)
    end
  end

  describe '#can_transition_to?' do
    it 'allows open -> investigating and open -> resolved' do
      incident = build(:incident, status: 'open')

      expect(incident.can_transition_to?('investigating')).to be(true)
      expect(incident.can_transition_to?('resolved')).to be(true)
      expect(incident.can_transition_to?('closed')).to be(false)
    end

    it 'allows nothing from closed' do
      expect(build(:incident, :closed).can_transition_to?('open')).to be(false)
    end
  end

  describe '#investigate!' do
    it 'moves an open incident to investigating' do
      incident = create(:incident, status: 'open')

      incident.investigate!

      expect(incident.reload.status).to eq('investigating')
    end

    it 'raises when the transition is not allowed' do
      incident = create(:incident, :resolved)

      expect { incident.investigate! }.to raise_error(described_class::InvalidTransitionError, /resolved/)
    end
  end

  describe '#resolve!' do
    it 'stamps resolved_at' do
      incident = create(:incident, :investigating)

      incident.resolve!

      expect(incident.reload.status).to eq('resolved')
      expect(incident.resolved_at).to be_present
    end
  end

  describe '#close!' do
    it 'stamps closed_at' do
      incident = create(:incident, :resolved)

      incident.close!

      expect(incident.reload.status).to eq('closed')
      expect(incident.closed_at).to be_present
    end

    it 'raises when closing an open incident' do
      expect { create(:incident, status: 'open').close! }
        .to raise_error(described_class::InvalidTransitionError)
    end
  end

  describe '#active?' do
    it 'is true for open and investigating' do
      expect(build(:incident, status: 'open')).to be_active
      expect(build(:incident, :investigating)).to be_active
    end

    it 'is false once resolved' do
      expect(build(:incident, :resolved)).not_to be_active
    end
  end

  describe 'devin session predicates' do
    it 'reports a session when an id is present' do
      incident = build(:incident, :with_devin_session)

      expect(incident.has_devin_session?).to be(true)
      expect(incident.has_active_devin_session?).to be(true)
    end

    it 'is not active when the session finished' do
      incident = build(:incident, :with_devin_session, devin_session_status: 'finished')

      expect(incident.has_active_devin_session?).to be(false)
    end

    it 'reports no session without an id' do
      incident = build(:incident)

      expect(incident.has_devin_session?).to be(false)
      expect(incident.has_active_devin_session?).to be(false)
    end
  end
end
