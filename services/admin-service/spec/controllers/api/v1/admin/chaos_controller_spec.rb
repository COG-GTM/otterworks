require 'rails_helper'

RSpec.describe Api::V1::Admin::ChaosController do
  let(:redis) { instance_double(Redis, setex: 'OK', keys: [], del: 0) }
  let(:chaos_secret) { nil }

  before do
    allow(Redis).to receive(:new).and_return(redis)
    allow(ChaosProbeService).to receive(:start)
    allow(ENV).to receive(:fetch).and_call_original
    allow(ENV).to receive(:fetch).with('CHAOS_SECRET', nil).and_return(chaos_secret)
  end

  def trigger_file_upload_chaos
    post :trigger, params: { service: 'file-service', scenario: 'upload_s3_error' }
  end

  def open_incident(service = 'file-service')
    Incident.create!(title: 'Upload failures', description: 'S3 errors', severity: 'high',
                     status: 'open', affected_service: service)
  end

  context 'without an authenticated caller' do
    it 'rejects trigger and sets no flag' do
      trigger_file_upload_chaos
      expect(response).to have_http_status(:forbidden)
      expect(redis).not_to have_received(:setex)
      expect(ChaosProbeService).not_to have_received(:start)
    end

    it 'rejects reset and leaves incidents open' do
      incident = open_incident
      delete :reset
      expect(response).to have_http_status(:forbidden)
      expect(redis).not_to have_received(:keys)
      expect(incident.reload.status).to eq('open')
    end
  end

  context 'with a non-admin caller' do
    before { set_jwt_env(request, role: 'user') }

    it 'rejects trigger' do
      trigger_file_upload_chaos
      expect(response).to have_http_status(:forbidden)
      expect(redis).not_to have_received(:setex)
    end

    it 'rejects reset' do
      incident = open_incident
      delete :reset
      expect(response).to have_http_status(:forbidden)
      expect(incident.reload.status).to eq('open')
    end
  end

  context 'with an admin caller and no CHAOS_SECRET configured' do
    let(:admin_id) { SecureRandom.uuid }

    before { set_jwt_env(request, user_id: admin_id, role: 'admin') }

    it 'sets the chaos flag, starts the probe and records an audit entry' do
      trigger_file_upload_chaos
      expect(response).to have_http_status(:ok)
      expect(redis).to have_received(:setex).with('chaos:file-service:upload_s3_error', 600, '1')
      expect(ChaosProbeService).to have_received(:start)
        .with(service: 'file-service', redis_key: 'chaos:file-service:upload_s3_error')
      log = AuditLog.find_by(action: 'chaos.triggered')
      expect(log.actor_id).to eq(admin_id)
      expect(log.changes_made['key']).to eq('chaos:file-service:upload_s3_error')
    end

    it 'still rejects unknown service/scenario pairs' do
      post :trigger, params: { service: 'file-service', scenario: 'suggest_500' }
      expect(response).to have_http_status(:unprocessable_entity)
      expect(redis).not_to have_received(:setex)
    end

    it 'clears flags, resolves chaos-service incidents and records an audit entry' do
      allow(redis).to receive(:keys).with('chaos:*').and_return(['chaos:file-service:upload_s3_error'])
      incident = open_incident
      other = open_incident('auth-service')

      delete :reset

      expect(response).to have_http_status(:ok)
      expect(redis).to have_received(:del).with('chaos:file-service:upload_s3_error')
      expect(incident.reload.status).to eq('resolved')
      expect(other.reload.status).to eq('open')
      log = AuditLog.find_by(action: 'chaos.reset')
      expect(log.actor_id).to eq(admin_id)
      expect(log.changes_made['resolved_incidents']).to eq([incident.id])
    end
  end

  context 'with an admin caller and CHAOS_SECRET configured' do
    let(:chaos_secret) { 'chaos-test-secret' }

    before { set_jwt_env(request, role: 'super_admin') }

    it 'rejects a missing X-Chaos-Secret' do
      trigger_file_upload_chaos
      expect(response).to have_http_status(:unauthorized)
      expect(redis).not_to have_received(:setex)
    end

    it 'rejects a wrong X-Chaos-Secret' do
      request.headers['X-Chaos-Secret'] = 'wrong'
      delete :reset
      expect(response).to have_http_status(:unauthorized)
      expect(redis).not_to have_received(:keys)
    end

    it 'accepts the matching X-Chaos-Secret' do
      request.headers['X-Chaos-Secret'] = 'chaos-test-secret'
      trigger_file_upload_chaos
      expect(response).to have_http_status(:ok)
      expect(redis).to have_received(:setex)
    end
  end

  context 'with a non-admin caller holding the CHAOS_SECRET' do
    let(:chaos_secret) { 'chaos-test-secret' }

    before { set_jwt_env(request, role: 'editor') }

    it 'is still rejected' do
      request.headers['X-Chaos-Secret'] = 'chaos-test-secret'
      trigger_file_upload_chaos
      expect(response).to have_http_status(:forbidden)
      expect(redis).not_to have_received(:setex)
    end
  end
end
