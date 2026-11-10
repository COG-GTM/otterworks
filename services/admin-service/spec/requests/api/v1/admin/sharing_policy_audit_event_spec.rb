require 'rails_helper'

# OTW-69 (OTW-63 US5): Given a workspace policy changes, Then an audit event with old and new
# default, min and max values is sent to audit-service from the same point the local AuditLog is written.
RSpec.describe 'Sharing policy audit events' do
  let(:path) { '/api/v1/admin/sharing_policy' }
  let(:owner_id) { SecureRandom.uuid }
  let(:owner_headers) do
    auth_headers(user_id: owner_id, email: 'owner@otterworks.com', role: 'owner')
      .merge('Content-Type' => 'application/json')
  end

  before { allow(AuditEventPublisher).to receive(:publish_policy_changed).and_return(true) }

  def put_policy(body, headers: owner_headers)
    put path, params: body.to_json, headers: headers
  end

  it 'Given a workspace owner changes the policy, Then policy_changed is sent with actor, workspace and ' \
     'old and new default, min and max' do
    put_policy({ default_expiry_days: 14, min_expiry_days: 7, max_expiry_days: 60 })

    expect(response).to have_http_status(:ok)
    expect(AuditEventPublisher).to have_received(:publish_policy_changed).once.with(
      workspace_id: 'default',
      actor_id: owner_id,
      old_value: { default_expiry_days: 30, min_expiry_days: 1, max_expiry_days: 90 },
      new_value: { default_expiry_days: 14, min_expiry_days: 7, max_expiry_days: 60 }
    )
  end

  it 'Given a partial change, Then old and new carry all three values' do
    create(:sharing_policy, default_expiry_days: 10, min_expiry_days: 5, max_expiry_days: 20)

    put_policy({ default_expiry_days: 15 })

    expect(AuditEventPublisher).to have_received(:publish_policy_changed).once.with(
      hash_including(old_value: { default_expiry_days: 10, min_expiry_days: 5, max_expiry_days: 20 },
                     new_value: { default_expiry_days: 15, min_expiry_days: 5, max_expiry_days: 20 })
    )
  end

  it 'Given a PUT that changes nothing, Then no event is sent' do
    create(:sharing_policy, default_expiry_days: 14, min_expiry_days: 7, max_expiry_days: 60)

    put_policy({ default_expiry_days: 14 })

    expect(response).to have_http_status(:ok)
    expect(AuditEventPublisher).not_to have_received(:publish_policy_changed)
  end

  it 'Given an invalid change, Then it is rejected with 422 and no event is sent' do
    put_policy({ max_expiry_days: 91 })

    expect(response).to have_http_status(:unprocessable_entity)
    expect(AuditEventPublisher).not_to have_received(:publish_policy_changed)
  end

  it 'Given a non-owner, Then it is rejected with 403 and no event is sent' do
    put_policy({ default_expiry_days: 14 }, headers: auth_headers(role: 'viewer').merge('Content-Type' => 'application/json'))

    expect(response).to have_http_status(:forbidden)
    expect(AuditEventPublisher).not_to have_received(:publish_policy_changed)
  end

  it 'Given audit delivery fails, Then the policy is still saved and returned' do
    allow(AuditEventPublisher).to receive(:publish_policy_changed).and_return(false)

    put_policy({ default_expiry_days: 14 })

    expect(response).to have_http_status(:ok)
    expect(SharingPolicy.for_workspace.default_expiry_days).to eq(14)
  end
end
