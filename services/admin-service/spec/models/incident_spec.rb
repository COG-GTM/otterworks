require 'rails_helper'

RSpec.describe Incident do
  include ActiveSupport::Testing::TimeHelpers

  describe 'validations' do
    subject { build(:incident) }

    it { is_expected.to validate_presence_of(:title) }
    it { is_expected.to validate_length_of(:title).is_at_most(255) }
    it { is_expected.to validate_presence_of(:description) }
    it { is_expected.to validate_inclusion_of(:severity).in_array(described_class::SEVERITIES) }
    it { is_expected.to validate_inclusion_of(:status).in_array(described_class::STATUSES) }

    it 'allows a blank affected_service' do
      expect(build(:incident, affected_service: nil)).to be_valid
    end

    it 'rejects an unknown affected_service' do
      incident = build(:incident, affected_service: 'ghost-service')

      expect(incident).not_to be_valid
      expect(incident.errors[:affected_service]).to be_present
    end
  end

  describe 'scopes' do
    let!(:open_incident) { create(:incident, status: 'open', severity: 'low') }
    let!(:investigating) { create(:incident, :investigating, severity: 'critical') }
    let!(:closed) { create(:incident, :closed, severity: 'low') }

    it 'filters by status' do
      expect(described_class.by_status('open')).to contain_exactly(open_incident)
    end

    it 'filters by severity' do
      expect(described_class.by_severity('low')).to contain_exactly(open_incident, closed)
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

    it 'allows investigating -> resolved only' do
      incident = build(:incident, :investigating)

      expect(incident.can_transition_to?('resolved')).to be(true)
      expect(incident.can_transition_to?('investigating')).to be(false)
    end

    it 'allows nothing out of closed' do
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

      expect { incident.investigate! }
        .to raise_error(Incident::InvalidTransitionError, /Cannot transition from 'resolved' to 'investigating'/)
    end
  end

  describe '#resolve!' do
    it 'stamps resolved_at' do
      incident = create(:incident, :investigating)

      freeze_time do
        incident.resolve!

        expect(incident.reload.status).to eq('resolved')
        expect(incident.resolved_at).to eq(Time.current)
      end
    end
  end

  describe '#close!' do
    it 'stamps closed_at' do
      incident = create(:incident, :resolved)

      freeze_time do
        incident.close!

        expect(incident.reload.status).to eq('closed')
        expect(incident.closed_at).to eq(Time.current)
      end
    end

    it 'refuses to close an open incident' do
      incident = create(:incident, status: 'open')

      expect { incident.close! }.to raise_error(Incident::InvalidTransitionError)
      expect(incident.reload.closed_at).to be_nil
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

  describe '#has_devin_session?' do
    it 'reflects the presence of a session id' do
      expect(build(:incident, :with_devin_session).has_devin_session?).to be(true)
      expect(build(:incident).has_devin_session?).to be(false)
    end
  end

  describe '#has_active_devin_session?' do
    it 'is true only while the session is running' do
      expect(build(:incident, :with_devin_session).has_active_devin_session?).to be(true)
    end

    it 'is false when the session has finished' do
      incident = build(:incident, :with_devin_session, devin_session_status: 'finished')

      expect(incident.has_active_devin_session?).to be(false)
    end

    it 'is false without a session' do
      expect(build(:incident).has_active_devin_session?).to be(false)
    end
  end
end
