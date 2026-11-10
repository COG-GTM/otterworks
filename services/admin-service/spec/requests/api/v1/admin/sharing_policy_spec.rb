require 'rails_helper'

# Scenarios from OTW-68 (OTW-63 US2: workspace default and bounds).
RSpec.describe 'Sharing policy API' do
  let(:path) { '/api/v1/admin/sharing_policy' }
  let(:owner_id) { SecureRandom.uuid }
  let(:owner_headers) do
    auth_headers(user_id: owner_id, email: 'owner@otterworks.com', role: 'owner')
      .merge('Content-Type' => 'application/json')
  end

  def json
    response.parsed_body
  end

  def put_policy(body, headers: owner_headers)
    put path, params: body.to_json, headers: headers
  end

  describe 'GET /api/v1/admin/sharing_policy' do
    # US2 AC1: Given no policy has been configured, Then the default is 30 days, min 1 day, max 90 days.
    it 'Given no policy configured, Then returns default 30, min 1, max 90' do
      get path, headers: auth_headers(role: 'viewer')

      expect(response).to have_http_status(:ok)
      expect(json).to eq('default_expiry_days' => 30, 'min_expiry_days' => 1, 'max_expiry_days' => 90)
      expect(SharingPolicy.count).to eq(0)
    end

    it 'Given a stored policy, Then returns the stored values' do
      create(:sharing_policy, default_expiry_days: 14, min_expiry_days: 7, max_expiry_days: 60)

      get path, headers: auth_headers(role: 'viewer')

      expect(json).to eq('default_expiry_days' => 14, 'min_expiry_days' => 7, 'max_expiry_days' => 60)
    end

    it 'requires a bearer token' do
      get path

      expect(response).to have_http_status(:unauthorized)
    end
  end

  describe 'PUT /api/v1/admin/sharing_policy' do
    # US2 AC2: Given I am a workspace owner, When I set the default to D days, Then D must be between
    # the current min and max (and never above 90), or the change is rejected with 422.
    context 'Given I am a workspace owner, When I set the default to D days' do
      it 'Then a D within [min, max] is saved and returned with 200' do
        put_policy({ default_expiry_days: 14, min_expiry_days: 7, max_expiry_days: 60 })

        expect(response).to have_http_status(:ok)
        expect(json).to eq('default_expiry_days' => 14, 'min_expiry_days' => 7, 'max_expiry_days' => 60)
        expect(SharingPolicy.for_workspace.to_policy)
          .to eq(default_expiry_days: 14, min_expiry_days: 7, max_expiry_days: 60)
      end

      it 'Then a partial update is validated against the current bounds' do
        create(:sharing_policy, default_expiry_days: 10, min_expiry_days: 5, max_expiry_days: 20)

        put_policy({ default_expiry_days: 15 })
        expect(response).to have_http_status(:ok)
        expect(json['default_expiry_days']).to eq(15)

        put_policy({ default_expiry_days: 25 })
        expect(response).to have_http_status(:unprocessable_entity)
        expect(SharingPolicy.for_workspace.default_expiry_days).to eq(15)
      end

      {
        'default above max' => { default_expiry_days: 91, min_expiry_days: 1, max_expiry_days: 90 },
        'default below min' => { default_expiry_days: 3, min_expiry_days: 5, max_expiry_days: 90 },
        'max above 90' => { default_expiry_days: 30, min_expiry_days: 1, max_expiry_days: 91 },
        'min below 1' => { default_expiry_days: 30, min_expiry_days: 0, max_expiry_days: 90 },
        'min greater than max' => { default_expiry_days: 30, min_expiry_days: 40, max_expiry_days: 20 },
        'non-integer default' => { default_expiry_days: 'never', min_expiry_days: 1, max_expiry_days: 90 },
        'null default (no "never expire")' => { default_expiry_days: nil, min_expiry_days: 1, max_expiry_days: 90 }
      }.each do |label, body|
        it "Then #{label} is rejected with 422 and nothing changes" do
          put_policy(body)

          expect(response).to have_http_status(:unprocessable_entity)
          expect(json['error']).to eq('Validation failed')
          expect(json['details']).to be_present
          expect(SharingPolicy.count).to eq(0)
          expect(AuditLog.by_action('sharing_policy.updated').count).to eq(0)
        end
      end

      it 'Then an empty body is rejected with 422' do
        put_policy({})

        expect(response).to have_http_status(:unprocessable_entity)
      end
    end

    # US2 AC3: Given I change the default or bounds, Then only links created afterwards use the new values.
    # Existing links keep their expires_at (stored per link in document-service); this endpoint only changes
    # the policy that new links read, and records the old and new values.
    context 'Given I change the default or bounds' do
      it 'Then new reads see the new values and the audit log records old and new values' do
        put_policy({ default_expiry_days: 7, min_expiry_days: 1, max_expiry_days: 30 })

        get path, headers: auth_headers(role: 'viewer')
        expect(json).to eq('default_expiry_days' => 7, 'min_expiry_days' => 1, 'max_expiry_days' => 30)

        log = AuditLog.by_action('sharing_policy.updated').sole
        expect(log.resource_type).to eq('SharingPolicy')
        expect(log.resource_id).to eq(SharingPolicy.for_workspace.id)
        expect(log.actor_id).to eq(owner_id)
        expect(log.actor_email).to eq('owner@otterworks.com')
        expect(log.changes_made).to eq(
          'workspace_id' => 'default',
          'before' => { 'default_expiry_days' => 30, 'min_expiry_days' => 1, 'max_expiry_days' => 90 },
          'after' => { 'default_expiry_days' => 7, 'min_expiry_days' => 1, 'max_expiry_days' => 30 }
        )
      end

      it 'Then only the policy row changes and it is not applied retroactively' do
        put_policy({ default_expiry_days: 7, min_expiry_days: 1, max_expiry_days: 30 })
        policy = SharingPolicy.for_workspace
        expect(policy.updated_by).to eq(owner_id)
        expect(policy.workspace_id).to eq('default')

        put_policy({ default_expiry_days: 60, min_expiry_days: 30, max_expiry_days: 90 })
        logs = AuditLog.by_action('sharing_policy.updated').order(:created_at)
        expect(logs.count).to eq(2)
        expect(logs.last.changes_made['before']['default_expiry_days']).to eq(7)
        expect(logs.last.changes_made['after']['default_expiry_days']).to eq(60)
      end

      it 'Then a PUT that changes nothing writes no audit entry' do
        create(:sharing_policy)

        put_policy({ default_expiry_days: 30 })

        expect(response).to have_http_status(:ok)
        expect(AuditLog.by_action('sharing_policy.updated').count).to eq(0)
      end

      it 'Then a PUT of the defaults before any policy is configured persists nothing' do
        put_policy({ default_expiry_days: 30, min_expiry_days: 1, max_expiry_days: 90 })

        expect(response).to have_http_status(:ok)
        expect(json).to eq('default_expiry_days' => 30, 'min_expiry_days' => 1, 'max_expiry_days' => 90)
        expect(SharingPolicy.count).to eq(0)
        expect(AuditLog.by_action('sharing_policy.updated').count).to eq(0)
      end
    end

    # US2 AC4: Given I am not a workspace owner, When I try to change the policy, Then I get 403.
    context 'Given I am not a workspace owner, When I try to change the policy' do
      %w[editor viewer user].each do |role|
        it "Then a #{role} gets 403 and the policy is unchanged" do
          headers = auth_headers(role: role).merge('Content-Type' => 'application/json')

          put_policy({ default_expiry_days: 7, min_expiry_days: 1, max_expiry_days: 30 }, headers: headers)

          expect(response).to have_http_status(:forbidden)
          expect(SharingPolicy.count).to eq(0)
          expect(AuditLog.by_action('sharing_policy.updated').count).to eq(0)
        end
      end

      it 'Then a request without a token is rejected with 401' do
        put path, params: { default_expiry_days: 7 }.to_json, headers: { 'Content-Type' => 'application/json' }

        expect(response).to have_http_status(:unauthorized)
      end
    end
  end
end
