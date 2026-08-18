require 'rails_helper'

RSpec.describe Api::V1::Admin::SettingsController do
  before do
    set_jwt_env(request)
    allow(ENV).to receive(:fetch).and_call_original
    allow(ENV).to receive(:fetch).with('DEVIN_API_KEY', nil).and_return(nil)
    allow(ENV).to receive(:fetch).with('DEVIN_ORG_ID', nil).and_return(nil)
    allow(AdminSettingsService).to receive(:slack_bot_token).and_return(nil)
  end

  describe 'GET #devin_credentials' do
    it 'reports presence without exposing values' do
      allow(AdminSettingsService).to receive(:devin_credentials)
        .and_return({ api_key: 'sekrit-value-123', org_id: nil })

      get :devin_credentials
      expect(response).to have_http_status(:ok)
      body = response.parsed_body
      expect(body['api_key_configured']).to be(true)
      expect(body['org_id_configured']).to be(false)
      expect(response.body).not_to include('sekrit-value-123')
    end

    it 'reports a configured pair the Devin API rejects as invalid' do
      allow(AdminSettingsService).to receive(:devin_credentials)
        .and_return({ api_key: 'key', org_id: 'org-1' })
      allow(DevinSessionService).to receive(:verify_credentials)
        .and_return({ valid: false, error: 'Devin API returned 403' })

      get :devin_credentials, params: { verify: 'true' }
      body = response.parsed_body
      expect(body['source']).to eq('settings')
      expect(body['valid']).to be(false)
      expect(body['error']).to eq('Devin API returned 403')
    end
  end

  describe 'DELETE #destroy_devin_credentials' do
    it 'clears the stored credentials' do
      allow(AdminSettingsService).to receive(:clear_devin_credentials)
      allow(AdminSettingsService).to receive(:devin_credentials)
        .and_return({ api_key: nil, org_id: nil })

      delete :destroy_devin_credentials
      expect(response).to have_http_status(:ok)
      expect(AdminSettingsService).to have_received(:clear_devin_credentials)
      body = response.parsed_body
      expect(body['api_key_configured']).to be(false)
      expect(body['org_id_configured']).to be(false)
    end

    it 'keeps the response shape when the post-revoke status read fails' do
      allow(AdminSettingsService).to receive(:clear_devin_credentials).and_return(true)
      allow(DevinSessionService).to receive(:credentials_status).and_raise(StandardError, 'pg down')

      delete :destroy_devin_credentials
      expect(response).to have_http_status(:ok)
      body = response.parsed_body
      # nil, not false: the revoke happened but presence could not be read.
      expect(body).to include('api_key_configured' => nil, 'org_id_configured' => nil,
                              'status_unavailable' => true, 'legacy_cache_cleared' => true)
    end
  end

  describe 'PUT #update_devin_credentials' do
    it 'stores both credentials' do
      allow(AdminSettingsService).to receive(:set_devin_credentials)
      allow(AdminSettingsService).to receive(:devin_credentials)
        .and_return({ api_key: 'key', org_id: 'org-1' })
      allow(DevinSessionService).to receive(:verify_credentials).and_return({ valid: true })

      put :update_devin_credentials, params: { api_key: 'key', org_id: 'org-1' }
      expect(response).to have_http_status(:ok)
      expect(AdminSettingsService).to have_received(:set_devin_credentials)
        .with(api_key: 'key', org_id: 'org-1')
      body = response.parsed_body
      expect(body['api_key_configured']).to be(true)
      expect(body['org_id_configured']).to be(true)
    end

    it 'says so when the stored pair is shadowed by a higher-precedence source' do
      allow(AdminSettingsService).to receive(:set_devin_credentials)
      allow(DevinSessionService).to receive(:verify_credentials).and_return({ valid: true })
      allow(DevinSessionService).to receive(:credentials_status)
        .and_return({ api_key_configured: true, org_id_configured: true, source: 'env' })

      put :update_devin_credentials, params: { api_key: 'key', org_id: 'org-1' }
      expect(response).to have_http_status(:ok)
      expect(response.parsed_body['stored_pair_shadowed_by']).to eq('env')
    end

    it 'rejects a missing parameter' do
      put :update_devin_credentials, params: { api_key: 'key' }
      expect(response).to have_http_status(:bad_request)
    end

    it 'refuses an org id that would reshape the outbound Devin request' do
      allow(AdminSettingsService).to receive(:set_devin_credentials)
      allow(DevinSessionService).to receive(:verify_credentials)

      put :update_devin_credentials, params: { api_key: 'key', org_id: 'org-1/sessions/../../foo' }
      expect(response).to have_http_status(:bad_request)
      expect(DevinSessionService).not_to have_received(:verify_credentials)
      expect(AdminSettingsService).not_to have_received(:set_devin_credentials)
    end

    it 'refuses to store a pair the Devin API rejects' do
      allow(AdminSettingsService).to receive(:set_devin_credentials)
      allow(DevinSessionService).to receive(:verify_credentials)
        .and_return({ valid: false, error: 'Devin API returned 403' })

      put :update_devin_credentials, params: { api_key: 'bad', org_id: 'org-1' }
      expect(response).to have_http_status(:unprocessable_entity)
      expect(response.parsed_body['detail']).to eq('Devin API returned 403')
      expect(AdminSettingsService).not_to have_received(:set_devin_credentials)
    end

    it 'reports an unreachable Devin API separately from a rejected key' do
      allow(AdminSettingsService).to receive(:set_devin_credentials)
      allow(DevinSessionService).to receive(:verify_credentials)
        .and_return({ valid: false, unreachable: true, error: 'Devin API unreachable: timeout' })

      put :update_devin_credentials, params: { api_key: 'key', org_id: 'org-1' }
      expect(response).to have_http_status(:service_unavailable)
      expect(AdminSettingsService).not_to have_received(:set_devin_credentials)
    end

    it 'stores an unverifiable pair when forced' do
      allow(AdminSettingsService).to receive(:set_devin_credentials)
      allow(AdminSettingsService).to receive(:devin_credentials)
        .and_return({ api_key: 'key', org_id: 'org-1' })
      allow(DevinSessionService).to receive(:verify_credentials)

      put :update_devin_credentials, params: { api_key: 'key', org_id: 'org-1', force: 'true' }
      expect(response).to have_http_status(:ok)
      expect(DevinSessionService).not_to have_received(:verify_credentials)
    end
  end

  describe 'GET #slack_notifications' do
    it 'reports the toggle and webhook presence without exposing the URL' do
      allow(AdminSettingsService).to receive(:slack_notifications_enabled?).and_return(true)
      allow(AdminSettingsService).to receive(:slack_webhook_url)
        .and_return('https://hooks.slack.com/services/T/B/sekrit')

      get :slack_notifications
      expect(response).to have_http_status(:ok)
      body = response.parsed_body
      expect(body['enabled']).to be(true)
      expect(body['webhook_configured']).to be(true)
      expect(response.body).not_to include('sekrit')
    end

    it 'reports bot token presence without exposing the token' do
      allow(AdminSettingsService).to receive(:slack_notifications_enabled?).and_return(true)
      allow(AdminSettingsService).to receive(:slack_webhook_url).and_return(nil)
      allow(AdminSettingsService).to receive(:slack_bot_token).and_return('xoxb-sekrit-token')

      get :slack_notifications
      expect(response).to have_http_status(:ok)
      expect(response.parsed_body['bot_token_configured']).to be(true)
      expect(response.body).not_to include('xoxb-sekrit-token')
    end
  end

  describe 'PUT #update_slack_notifications' do
    before do
      allow(AdminSettingsService).to receive(:slack_notifications_enabled?).and_return(true)
      allow(AdminSettingsService).to receive(:slack_webhook_url).and_return(nil)
    end

    it 'stores the toggle and webhook URL' do
      allow(AdminSettingsService).to receive(:set_slack_notifications)
      allow(AdminSettingsService).to receive(:set_slack_webhook_url)

      put :update_slack_notifications,
          params: { enabled: false, webhook_url: 'https://hooks.slack.com/services/T/B/x' }
      expect(response).to have_http_status(:ok)
      expect(AdminSettingsService).to have_received(:set_slack_notifications).with(false)
      expect(AdminSettingsService).to have_received(:set_slack_webhook_url)
        .with('https://hooks.slack.com/services/T/B/x')
    end

    it 'stores the bot token' do
      allow(AdminSettingsService).to receive(:set_slack_bot_token)

      put :update_slack_notifications, params: { bot_token: 'xoxb-1234-abcd' }
      expect(response).to have_http_status(:ok)
      expect(AdminSettingsService).to have_received(:set_slack_bot_token).with('xoxb-1234-abcd')
    end

    it 'rejects a malformed bot token' do
      allow(AdminSettingsService).to receive(:set_slack_bot_token)

      put :update_slack_notifications, params: { bot_token: 'not-a-token' }
      expect(response).to have_http_status(:bad_request)
      expect(AdminSettingsService).not_to have_received(:set_slack_bot_token)
    end

    it 'rejects a non-bot xoxp- token' do
      allow(AdminSettingsService).to receive(:set_slack_bot_token)

      put :update_slack_notifications, params: { bot_token: 'xoxp-user-token' }
      expect(response).to have_http_status(:bad_request)
      expect(AdminSettingsService).not_to have_received(:set_slack_bot_token)
    end

    it 'rejects a request with no parameters' do
      put :update_slack_notifications
      expect(response).to have_http_status(:bad_request)
    end

    it 'rejects a non-Slack webhook URL' do
      put :update_slack_notifications, params: { webhook_url: 'http://169.254.169.254/latest' }
      expect(response).to have_http_status(:bad_request)
    end
  end

  describe 'DELETE #destroy_slack_notifications' do
    it 'clears the stored webhook URL and bot token without touching the toggle' do
      allow(AdminSettingsService).to receive(:clear_slack_credentials)
      allow(AdminSettingsService).to receive(:set_slack_notifications)
      allow(AdminSettingsService).to receive(:slack_notifications_enabled?).and_return(true)
      allow(AdminSettingsService).to receive(:slack_webhook_url).and_return(nil)

      delete :destroy_slack_notifications
      expect(response).to have_http_status(:ok)
      expect(AdminSettingsService).to have_received(:clear_slack_credentials)
      expect(AdminSettingsService).not_to have_received(:set_slack_notifications)
      expect(response.parsed_body['enabled']).to be(true)
    end
  end

  describe 'role enforcement' do
    it 'forbids settings writes for non-admin roles' do
      set_jwt_env(request, role: 'viewer')
      allow(AdminSettingsService).to receive(:set_slack_notifications)

      put :update_slack_notifications, params: { enabled: false }
      expect(response).to have_http_status(:forbidden)
      expect(AdminSettingsService).not_to have_received(:set_slack_notifications)
    end

    it 'refuses to spend a Devin API call on a non-admin verify request' do
      set_jwt_env(request, role: 'viewer')
      allow(AdminSettingsService).to receive(:devin_credentials)
        .and_return({ api_key: 'key', org_id: 'org-1' })
      allow(DevinSessionService).to receive(:verify_credentials)

      get :devin_credentials, params: { verify: 'true' }
      expect(response).to have_http_status(:forbidden)
      expect(DevinSessionService).not_to have_received(:verify_credentials)
    end

    it 'still reports credential presence to non-admin roles' do
      set_jwt_env(request, role: 'viewer')
      allow(AdminSettingsService).to receive(:devin_credentials)
        .and_return({ api_key: 'key', org_id: 'org-1' })

      get :devin_credentials
      expect(response).to have_http_status(:ok)
    end

    it 'allows settings reads for non-admin roles' do
      set_jwt_env(request, role: 'viewer')
      allow(AdminSettingsService).to receive(:slack_notifications_enabled?).and_return(true)
      allow(AdminSettingsService).to receive(:slack_webhook_url).and_return(nil)

      get :slack_notifications
      expect(response).to have_http_status(:ok)
    end
  end
end
