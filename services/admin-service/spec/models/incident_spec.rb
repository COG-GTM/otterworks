require 'rails_helper'

RSpec.describe Incident do
  subject(:incident) { build(:incident) }

  describe 'validations' do
    it { is_expected.to validate_presence_of(:title) }
    it { is_expected.to validate_presence_of(:description) }
    it { is_expected.to validate_length_of(:title).is_at_most(255) }
    it { is_expected.to validate_inclusion_of(:severity).in_array(described_class::SEVERITIES) }
    it { is_expected.to validate_inclusion_of(:status).in_array(described_class::STATUSES) }

    it 'allows a blank affected_service' do
      incident.affected_service = ''
      expect(incident).to be_valid
    end

    it 'rejects an unknown affected_service' do
      incident.affected_service = 'nope-service'
      expect(incident).not_to be_valid
      expect(incident.errors[:affected_service]).to be_present
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
      expect(described_class.by_severity('low')).to contain_exactly(open_incident, resolved)
    end

    it 'returns only open and investigating incidents as active' do
      expect(described_class.active).to contain_exactly(open_incident, investigating)
    end
  end

  describe '#can_transition_to?' do
    it 'allows open -> investigating and open -> resolved' do
      incident.status = 'open'
      expect(incident.can_transition_to?('investigating')).to be(true)
      expect(incident.can_transition_to?('resolved')).to be(true)
    end

    it 'rejects open -> closed' do
      incident.status = 'open'
      expect(incident.can_transition_to?('closed')).to be(false)
    end

    it 'rejects every transition out of closed' do
      incident.status = 'closed'
      expect(described_class::STATUSES.map { |s| incident.can_transition_to?(s) }.uniq).to eq([false])
    end
  end

  describe 'transition helpers' do
    it 'moves an open incident to investigating' do
      record = create(:incident, status: 'open')
      record.investigate!
      expect(record.reload.status).to eq('investigating')
    end

    it 'stamps resolved_at when resolving' do
      record = create(:incident, :investigating)
      record.resolve!
      expect(record.reload.status).to eq('resolved')
      expect(record.resolved_at).to be_present
    end

    it 'stamps closed_at when closing a resolved incident' do
      record = create(:incident, :resolved)
      record.close!
      expect(record.reload.status).to eq('closed')
      expect(record.closed_at).to be_present
    end

    it 'raises InvalidTransitionError on an illegal transition' do
      record = create(:incident, status: 'open')
      expect { record.close! }
        .to raise_error(described_class::InvalidTransitionError, /Cannot transition from 'open' to 'closed'/)
      expect(record.reload.status).to eq('open')
    end
  end

  describe '#active?' do
    it 'is true for open and investigating' do
      expect(build(:incident, status: 'open').active?).to be(true)
      expect(build(:incident, :investigating).active?).to be(true)
    end

    it 'is false once resolved' do
      expect(build(:incident, :resolved).active?).to be(false)
    end
  end

  describe 'devin session predicates' do
    it 'reports no session when devin_session_id is blank' do
      expect(incident.has_devin_session?).to be(false)
      expect(incident.has_active_devin_session?).to be(false)
    end

    it 'reports an active session when the status is running' do
      record = build(:incident, :with_devin_session)
      expect(record.has_devin_session?).to be(true)
      expect(record.has_active_devin_session?).to be(true)
    end

    it 'reports an inactive session when the status is not running' do
      record = build(:incident, :with_devin_session, devin_session_status: 'finished')
      expect(record.has_devin_session?).to be(true)
      expect(record.has_active_devin_session?).to be(false)
    end
  end
end
