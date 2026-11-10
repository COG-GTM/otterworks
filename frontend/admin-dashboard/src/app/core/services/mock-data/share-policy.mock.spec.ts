import { TestBed } from '@angular/core/testing';
import { HTTP_INTERCEPTORS, HttpClient, provideHttpClient, withInterceptorsFromDi } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { SharePolicyMockInterceptor, SHARE_POLICY_MOCK_STORAGE_KEY } from './share-policy.mock';
import { SHARE_POLICY_URL } from '../share-policy.service';

describe('SharePolicyMockInterceptor (dev-only mock of the share-policy contract)', () => {
  let http: HttpClient;
  let backend: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptorsFromDi()),
        provideHttpClientTesting(),
        { provide: HTTP_INTERCEPTORS, useClass: SharePolicyMockInterceptor, multi: true },
      ],
    });
    http = TestBed.inject(HttpClient);
    backend = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    localStorage.removeItem(SHARE_POLICY_MOCK_STORAGE_KEY);
    backend.verify();
  });

  it('passes requests through to the real API when the switch is off', () => {
    http.get(SHARE_POLICY_URL).subscribe();
    backend.expectOne(SHARE_POLICY_URL).flush({});
  });

  it('serves built-in defaults, persists a valid PUT and rejects an invalid one with 422', (done) => {
    localStorage.setItem(SHARE_POLICY_MOCK_STORAGE_KEY, 'true');
    http.get<any>(SHARE_POLICY_URL).subscribe(policy => {
      expect(policy.default_expiry_days).toBe(7);
      http.put<any>(SHARE_POLICY_URL, { default_expiry_days: 14, min_expiry_days: 1, max_expiry_days: 30 })
        .subscribe(saved => {
          expect(saved.default_expiry_days).toBe(14);
          expect(saved.updated_at).toBeTruthy();
          http.put(SHARE_POLICY_URL, { default_expiry_days: 7, min_expiry_days: 1, max_expiry_days: 400 })
            .subscribe({
              error: err => {
                expect(err.status).toBe(422);
                expect(err.error.detail).toContain('365');
                backend.expectNone(SHARE_POLICY_URL);
                done();
              },
            });
        });
    });
  });
});
