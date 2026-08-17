require 'rails_helper'

RSpec.describe IncidentSerializer do
  let(:incident) { create(:incident, :with_devin_session, status: 'investigating') }
  let(:payload) { described_class.new(incident).as_json }

  it 'exposes the incident attributes' do
    expect(payload).to include(
      id: incident.id,
      title: incident.title,
      severity: incident.severity,
      status: 'investigating',
      affected_service: incident.affected_service,
      devin_session_id: incident.devin_session_id,
      devin_session_url: incident.devin_session_url,
      devin_session_status: 'running'
    )
  end

  it 'exposes the computed active flag' do
    expect(payload[:active]).to be(true)
    expect(described_class.new(create(:incident, :resolved)).as_json[:active]).to be(false)
  end
end
