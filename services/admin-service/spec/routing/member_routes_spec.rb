require 'rails_helper'

RSpec.describe 'Admin member routes', type: :routing do
  let(:id) { '7b0f0c4e-1a2b-4c3d-9e8f-0123456789ab' }

  it 'routes PUT users/:id/suspend to users#suspend' do
    expect(put: "/api/v1/admin/users/#{id}/suspend").to route_to('api/v1/admin/users#suspend', id: id)
  end

  it 'routes PUT users/:id/activate to users#activate' do
    expect(put: "/api/v1/admin/users/#{id}/activate").to route_to('api/v1/admin/users#activate', id: id)
  end

  it 'routes POST incidents/:id/trigger_session to incidents#trigger_session' do
    expect(post: "/api/v1/admin/incidents/#{id}/trigger_session")
      .to route_to('api/v1/admin/incidents#trigger_session', id: id)
  end

  it 'keeps the member route helper names' do
    helpers = Rails.application.routes.url_helpers
    expect(helpers.suspend_api_v1_admin_user_path(id)).to eq("/api/v1/admin/users/#{id}/suspend")
    expect(helpers.activate_api_v1_admin_user_path(id)).to eq("/api/v1/admin/users/#{id}/activate")
    expect(helpers.trigger_session_api_v1_admin_incident_path(id))
      .to eq("/api/v1/admin/incidents/#{id}/trigger_session")
  end
end
