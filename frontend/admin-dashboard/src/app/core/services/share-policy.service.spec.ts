import { TestBed } from '@angular/core/testing';
import { HttpClientTestingModule, HttpTestingController } from '@angular/common/http/testing';
import { SharePolicyService, SHARE_POLICY_URL } from './share-policy.service';
import { MOCK_SHARE_POLICY_RESPONSE } from './mock-data/share-policy.mock';

describe('SharePolicyService (OTW-81)', () => {
  let service: SharePolicyService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [HttpClientTestingModule] });
    service = TestBed.inject(SharePolicyService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('US1/AC1: GETs the workspace policy from document-service and maps it', () => {
    let result: unknown;
    service.getPolicy().subscribe(p => (result = p));

    const req = http.expectOne(SHARE_POLICY_URL);
    expect(req.request.method).toBe('GET');
    expect(SHARE_POLICY_URL).toBe('/api/v1/documents/share-policy');
    req.flush(MOCK_SHARE_POLICY_RESPONSE);

    expect(result).toEqual({
      workspaceId: 'default', defaultExpiryDays: 7, minExpiryDays: 1, maxExpiryDays: 30,
      updatedBy: null, updatedAt: null,
    });
  });

  it('US1/US2: PUTs default/min/max in the contract body shape and maps the response', () => {
    let result: any;
    service.updatePolicy({ defaultExpiryDays: 14, minExpiryDays: 2, maxExpiryDays: 60 }).subscribe(p => (result = p));

    const req = http.expectOne(SHARE_POLICY_URL);
    expect(req.request.method).toBe('PUT');
    expect(req.request.body).toEqual({ default_expiry_days: 14, min_expiry_days: 2, max_expiry_days: 60 });
    req.flush({
      ...MOCK_SHARE_POLICY_RESPONSE, default_expiry_days: 14, min_expiry_days: 2, max_expiry_days: 60,
      updated_by: 'u-1', updated_at: '2026-11-10T17:00:00Z',
    });

    expect(result.defaultExpiryDays).toBe(14);
    expect(result.minExpiryDays).toBe(2);
    expect(result.maxExpiryDays).toBe(60);
    expect(result.updatedBy).toBe('u-1');
    expect(result.updatedAt).toBe('2026-11-10T17:00:00Z');
  });

  it('AC3: surfaces a 422 from the server to the caller', () => {
    let status = 0;
    service.updatePolicy({ defaultExpiryDays: 7, minExpiryDays: 1, maxExpiryDays: 400 })
      .subscribe({ error: e => (status = e.status) });

    http.expectOne(SHARE_POLICY_URL).flush(
      { detail: 'max_expiry_days must be at most 365' },
      { status: 422, statusText: 'Unprocessable Entity' },
    );
    expect(status).toBe(422);
  });
});
