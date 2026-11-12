require 'rails_helper'

RSpec.describe Api::V1::Admin::IncidentsController do
  before { set_jwt_env(request) }

  describe 'PUT #update' do
    it 'moves an open incident to investigating' do
      incident = create(:incident)
      put :update, params: { id: incident.id, incident: { status: 'investigating' } }
      expect(response).to have_http_status(:ok)
      expect(incident.reload.status).to eq('investigating')
    end

    it 'resolves an investigating incident' do
      incident = create(:incident, :investigating)
      put :update, params: { id: incident.id, incident: { status: 'resolved' } }
      expect(response).to have_http_status(:ok)
      expect(incident.reload.status).to eq('resolved')
      expect(incident.resolved_at).to be_present
    end

    it 'closes a resolved incident' do
      incident = create(:incident, :resolved)
      put :update, params: { id: incident.id, incident: { status: 'closed' } }
      expect(response).to have_http_status(:ok)
      expect(incident.reload.status).to eq('closed')
      expect(incident.closed_at).to be_present
    end

    it 'rejects a transition the state machine does not allow' do
      incident = create(:incident, :resolved)
      put :update, params: { id: incident.id, incident: { status: 'investigating' } }
      expect(response).to have_http_status(:unprocessable_entity)
      expect(incident.reload.status).to eq('resolved')
    end

    it 'rejects a status with no handler instead of silently succeeding' do
      incident = create(:incident)
      allow_any_instance_of(Incident).to receive(:can_transition_to?).and_return(true)

      expect do
        put :update, params: { id: incident.id, incident: { status: 'open' } }
      end.not_to change(AuditLog, :count)

      expect(response).to have_http_status(:unprocessable_entity)
      body = JSON.parse(response.body)
      expect(body['error']).to eq('Invalid status transition')
      expect(incident.reload.status).to eq('open')
    end
  end
end
