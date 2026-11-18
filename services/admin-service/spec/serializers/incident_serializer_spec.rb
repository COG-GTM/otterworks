require 'rails_helper'

RSpec.describe IncidentSerializer do
  it 'serializes incident attributes including the derived active flag' do
    incident = create(:incident, :with_session)
    json = described_class.new(incident).as_json

    expect(json).to include(
      id: incident.id,
      title: incident.title,
      severity: 'high',
      status: 'open',
      affected_service: 'file-service',
      devin_session_id: incident.devin_session_id,
      devin_session_status: 'running',
      active: true
    )
    expect(json.keys).to include(:reporter_id, :resolved_at, :closed_at, :created_at, :updated_at, :devin_session_url)
  end

  it 'reports active false for a resolved incident' do
    expect(described_class.new(build(:incident, :resolved)).as_json[:active]).to be false
  end
end
