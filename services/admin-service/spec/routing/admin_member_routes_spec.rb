require 'rails_helper'

RSpec.describe 'Admin member routes', type: :routing do
  it 'routes PUT /api/v1/admin/users/:id/suspend to users#suspend' do
    expect(put: '/api/v1/admin/users/abc-123/suspend')
      .to route_to('api/v1/admin/users#suspend', id: 'abc-123')
  end

  it 'routes PUT /api/v1/admin/users/:id/activate to users#activate' do
    expect(put: '/api/v1/admin/users/abc-123/activate')
      .to route_to('api/v1/admin/users#activate', id: 'abc-123')
  end

  it 'routes POST /api/v1/admin/incidents/:id/trigger_session to incidents#trigger_session' do
    expect(post: '/api/v1/admin/incidents/abc-123/trigger_session')
      .to route_to('api/v1/admin/incidents#trigger_session', id: 'abc-123')
  end

  it 'keeps the member route helper names' do
    helpers = Rails.application.routes.url_helpers
    expect(helpers.suspend_api_v1_admin_user_path('abc-123')).to eq('/api/v1/admin/users/abc-123/suspend')
    expect(helpers.activate_api_v1_admin_user_path('abc-123')).to eq('/api/v1/admin/users/abc-123/activate')
    expect(helpers.trigger_session_api_v1_admin_incident_path('abc-123'))
      .to eq('/api/v1/admin/incidents/abc-123/trigger_session')
  end
end
