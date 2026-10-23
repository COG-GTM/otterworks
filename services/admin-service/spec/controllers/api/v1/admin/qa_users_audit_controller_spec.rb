require 'rails_helper'

# QA admin-audit unit layer: user lifecycle authz + audit trail, audit-log
# reads and quota reads. Findings referenced as QA-AA-N are documented in
# docs/qa/admin-audit.md.
RSpec.describe Api::V1::Admin::UsersController, type: :controller do
  let(:actor_id) { SecureRandom.uuid }
  let(:actor_email) { 'qa-admin@otterworks.test' }

  before { set_jwt_env(request, user_id: actor_id, email: actor_email, role: 'admin') }

  describe 'role-based access' do
    let!(:target) { create(:admin_user) }

    %w[admin super_admin owner].each do |role|
      it "allows #{role} to view a user" do
        set_jwt_env(request, role: role)
        get :show, params: { id: target.id }
        expect(response).to have_http_status(:ok)
      end
    end

    %w[editor viewer user].each do |role|
      it "forbids #{role} from suspending a user" do
        set_jwt_env(request, role: role)
        put :suspend, params: { id: target.id }
        expect(response).to have_http_status(:forbidden)
        expect(target.reload.status).to eq('active')
      end

      it "forbids #{role} from changing a role" do
        set_jwt_env(request, role: role)
        put :update, params: { id: target.id, user: { role: 'super_admin' } }
        expect(response).to have_http_status(:forbidden)
        expect(target.reload.role).to eq('viewer')
      end
    end

    it 'forbids requests without any role' do
      request.env['jwt.user_role'] = nil
      get :index
      expect(response).to have_http_status(:forbidden)
    end
  end

  describe 'PUT #update (role change)' do
    let!(:target) { create(:admin_user, role: 'viewer') }

    it 'changes the role and records actor + before/after in the audit log' do
      expect do
        put :update, params: { id: target.id, user: { role: 'editor' } }
      end.to change(AuditLog, :count).by(1)

      expect(response).to have_http_status(:ok)
      expect(JSON.parse(response.body)['role']).to eq('editor')
      log = AuditLog.last
      expect(log.action).to eq('user.updated')
      expect(log.resource_id).to eq(target.id)
      expect(log.actor_id).to eq(actor_id)
      expect(log.actor_email).to eq(actor_email)
      expect(log.changes_made.to_s).to include('editor')
    end

    it 'rejects an unknown role with 422 and writes no audit log' do
      expect do
        put :update, params: { id: target.id, user: { role: 'god_mode' } }
      end.not_to change(AuditLog, :count)
      expect(response).to have_http_status(:unprocessable_entity)
      expect(target.reload.role).to eq('viewer')
    end

    it 'ignores non-permitted attributes such as status' do
      put :update, params: { id: target.id, user: { status: 'deleted', display_name: 'Renamed' } }
      expect(response).to have_http_status(:ok)
      expect(target.reload.status).to eq('active')
      expect(target.display_name).to eq('Renamed')
    end

    it 'returns 404 for an unknown user' do
      put :update, params: { id: SecureRandom.uuid, user: { role: 'editor' } }
      expect(response).to have_http_status(:not_found)
    end
  end

  describe 'suspend / activate lifecycle' do
    let!(:target) { create(:admin_user) }

    it 'suspends with a reason and audits user.suspended with the actor' do
      put :suspend, params: { id: target.id, reason: 'QA policy test' }
      expect(response).to have_http_status(:ok)
      target.reload
      expect(target.status).to eq('suspended')
      expect(target.suspended_reason).to eq('QA policy test')
      expect(target.suspended_at).to be_within(1.minute).of(Time.current)
      log = AuditLog.where(action: 'user.suspended', resource_id: target.id).last
      expect(log.actor_id).to eq(actor_id)
      expect(log.changes_made['reason']).to eq('QA policy test')
    end

    it 'reactivates and clears suspension fields, auditing user.activated' do
      target.suspend!(reason: 'x')
      put :activate, params: { id: target.id }
      expect(response).to have_http_status(:ok)
      target.reload
      expect(target.status).to eq('active')
      expect(target.suspended_at).to be_nil
      expect(target.suspended_reason).to be_nil
      expect(AuditLog.where(action: 'user.activated', resource_id: target.id, actor_id: actor_id)).to exist
    end

    it 'soft-deletes on DELETE and audits user.deleted' do
      delete :destroy, params: { id: target.id }
      expect(response).to have_http_status(:no_content).or have_http_status(:ok)
      expect(target.reload.status).to eq('deleted')
      expect(AuditLog.where(action: 'user.deleted', resource_id: target.id)).to exist
    end

    it 'does not reactivate a soft-deleted user (QA-AA-5)' do
      pending 'QA-AA-5: activate! has no state guard; PUT /users/:id/activate revives deleted users'
      deleted = create(:admin_user, :deleted)
      put :activate, params: { id: deleted.id }
      expect(response).to have_http_status(:unprocessable_entity).or have_http_status(:conflict)
      expect(deleted.reload.status).to eq('deleted')
    end
  end

  describe 'GET #index search' do
    it 'treats LIKE wildcards in q literally' do
      create_list(:admin_user, 3)
      get :index, params: { q: '%' }
      expect(JSON.parse(response.body)['users']).to be_empty
    end

    it 'searches case-insensitively by display name' do
      user = create(:admin_user, display_name: 'Quinn Auditor')
      get :index, params: { q: 'quinn aud' }
      ids = JSON.parse(response.body)['users'].map { |u| u['id'] }
      expect(ids).to eq([user.id])
    end
  end
end

RSpec.describe Api::V1::Admin::AuditLogsController, type: :controller do
  before { set_jwt_env(request, role: 'admin') }

  describe 'GET #index filters' do
    let(:actor) { SecureRandom.uuid }
    let!(:mine) { create(:audit_log, actor_id: actor, action: 'user.suspended') }
    let!(:other) { create(:audit_log, action: 'feature_flag.created', resource_type: 'FeatureFlag') }

    it 'filters by actor_id' do
      get :index, params: { actor_id: actor }
      ids = JSON.parse(response.body)['audit_logs'].map { |l| l['id'] }
      expect(ids).to eq([mine.id])
    end

    it 'filters by action_type' do
      get :index, params: { action_type: 'feature_flag.created' }
      ids = JSON.parse(response.body)['audit_logs'].map { |l| l['id'] }
      expect(ids).to eq([other.id])
    end

    it 'filters by resource_type + resource_id' do
      get :index, params: { resource_type: 'AdminUser', resource_id: mine.resource_id }
      ids = JSON.parse(response.body)['audit_logs'].map { |l| l['id'] }
      expect(ids).to eq([mine.id])
    end

    it 'returns most recent first' do
      newest = create(:audit_log, created_at: 1.minute.from_now)
      get :index
      expect(JSON.parse(response.body)['audit_logs'].first['id']).to eq(newest.id)
    end

    it 'applies until as an upper bound' do
      old = create(:audit_log, created_at: 3.days.ago)
      get :index, params: { until: 2.days.ago.iso8601 }
      ids = JSON.parse(response.body)['audit_logs'].map { |l| l['id'] }
      expect(ids).to eq([old.id])
    end

    it 'returns 400 for an unparseable since' do
      get :index, params: { since: 'not-a-date' }
      expect(response).to have_http_status(:bad_request)
    end

    it 'returns 404 for an unknown audit log id' do
      get :show, params: { id: SecureRandom.uuid }
      expect(response).to have_http_status(:not_found)
    end
  end

  describe 'authorization' do
    it 'forbids non-admin roles from reading the admin audit trail (QA-AA-2)' do
      pending 'QA-AA-2: AuditLogsController has no require_admin!; any authenticated role can read it'
      create(:audit_log)
      set_jwt_env(request, role: 'viewer')
      get :index
      expect(response).to have_http_status(:forbidden)
    end
  end
end

RSpec.describe Api::V1::Admin::QuotasController, type: :controller do
  let!(:quota) { create(:storage_quota) }

  it 'lets an admin read any quota' do
    set_jwt_env(request, role: 'admin')
    get :show, params: { user_id: quota.user_id }
    expect(response).to have_http_status(:ok)
  end

  it 'forbids a viewer from updating a quota' do
    set_jwt_env(request, role: 'viewer')
    put :update, params: { user_id: quota.user_id, quota: { quota_bytes: 1 } }
    expect(response).to have_http_status(:forbidden)
  end

  it 'forbids a non-admin from reading another user quota (QA-AA-3)' do
    pending 'QA-AA-3: QuotasController#show has no admin/ownership check (IDOR)'
    set_jwt_env(request, user_id: SecureRandom.uuid, role: 'viewer')
    get :show, params: { user_id: quota.user_id }
    expect(response).to have_http_status(:forbidden)
  end
end
