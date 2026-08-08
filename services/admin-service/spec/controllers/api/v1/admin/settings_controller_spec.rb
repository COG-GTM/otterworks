require 'rails_helper'

RSpec.describe Api::V1::Admin::SettingsController do
  before do
    allow(ENV).to receive(:fetch).and_call_original
    allow(ENV).to receive(:fetch).with('DEVIN_API_KEY', nil).and_return(nil)
    allow(ENV).to receive(:fetch).with('DEVIN_ORG_ID', nil).and_return(nil)
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
  end

  describe 'PUT #update_devin_credentials' do
    it 'stores both credentials' do
      allow(AdminSettingsService).to receive(:set_devin_credentials)
      allow(AdminSettingsService).to receive(:devin_credentials)
        .and_return({ api_key: 'key', org_id: 'org-1' })

      put :update_devin_credentials, params: { api_key: 'key', org_id: 'org-1' }
      expect(response).to have_http_status(:ok)
      expect(AdminSettingsService).to have_received(:set_devin_credentials)
        .with(api_key: 'key', org_id: 'org-1')
      body = response.parsed_body
      expect(body['api_key_configured']).to be(true)
      expect(body['org_id_configured']).to be(true)
    end

    it 'rejects a missing parameter' do
      put :update_devin_credentials, params: { api_key: 'key' }
      expect(response).to have_http_status(:bad_request)
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

    it 'rejects a request with neither parameter' do
      put :update_slack_notifications
      expect(response).to have_http_status(:bad_request)
    end

    it 'rejects a non-Slack webhook URL' do
      put :update_slack_notifications, params: { webhook_url: 'http://169.254.169.254/latest' }
      expect(response).to have_http_status(:bad_request)
    end
  end

  describe 'DELETE #destroy_slack_notifications' do
    it 'clears the stored webhook URL without touching the toggle' do
      allow(AdminSettingsService).to receive(:clear_slack_webhook_url)
      allow(AdminSettingsService).to receive(:slack_notifications_enabled?).and_return(true)
      allow(AdminSettingsService).to receive(:slack_webhook_url).and_return(nil)

      delete :destroy_slack_notifications
      expect(response).to have_http_status(:ok)
      expect(AdminSettingsService).to have_received(:clear_slack_webhook_url)
      expect(AdminSettingsService).not_to have_received(:slack_notifications_enabled?).with(anything)
      expect(response.parsed_body['enabled']).to be(true)
    end
  end
end
