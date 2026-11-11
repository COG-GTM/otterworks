require 'rails_helper'

RSpec.shared_examples 'an admin-only read endpoint' do |action, params = {}|
  %w[user viewer editor].each do |role|
    it "forbids #{action} for the #{role} role" do
      set_jwt_env(request, role: role)
      get action, params: params
      expect(response).to have_http_status(:forbidden)
      expect(response.parsed_body['error']).to eq('Admin role required')
    end
  end

  it "forbids #{action} when the token carries no role" do
    set_jwt_env(request, role: nil)
    get action, params: params
    expect(response).to have_http_status(:forbidden)
  end
end

RSpec.describe Api::V1::Admin::AuditLogsController, type: :controller do
  it_behaves_like 'an admin-only read endpoint', :index
  it_behaves_like 'an admin-only read endpoint', :show, { id: 1 }
end

RSpec.describe Api::V1::Admin::IncidentsController, type: :controller do
  it_behaves_like 'an admin-only read endpoint', :index
  it_behaves_like 'an admin-only read endpoint', :show, { id: SecureRandom.uuid }
end

RSpec.describe Api::V1::Admin::QuotasController, type: :controller do
  it_behaves_like 'an admin-only read endpoint', :show, { user_id: SecureRandom.uuid }
end

RSpec.describe Api::V1::Admin::FeaturesController, type: :controller do
  it_behaves_like 'an admin-only read endpoint', :index
  it_behaves_like 'an admin-only read endpoint', :show, { id: 1 }
end

RSpec.describe Api::V1::Admin::ConfigController, type: :controller do
  it_behaves_like 'an admin-only read endpoint', :index
  it_behaves_like 'an admin-only read endpoint', :show, { id: 1 }
end

RSpec.describe Api::V1::Admin::AnnouncementsController, type: :controller do
  it_behaves_like 'an admin-only read endpoint', :index
  it_behaves_like 'an admin-only read endpoint', :show, { id: 1 }
end

RSpec.describe Api::V1::Admin::MetricsController, type: :controller do
  it_behaves_like 'an admin-only read endpoint', :summary
end

RSpec.describe Api::V1::Admin::HealthController, type: :controller do
  it 'allows admins to read service health' do
    allow(HealthChecker).to receive(:check_all).and_return({ services: [] })
    set_jwt_env(request)
    get :services
    expect(response).to have_http_status(:ok)
  end

  it_behaves_like 'an admin-only read endpoint', :services
end
