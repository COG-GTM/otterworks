import { TestBed, fakeAsync, tick } from '@angular/core/testing';
import { HttpClientTestingModule, HttpTestingController } from '@angular/common/http/testing';
import { AdminApiService } from './admin-api.service';

describe('AdminApiService', () => {
  let service: AdminApiService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule],
    });
    service = TestBed.inject(AdminApiService);
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('should return dashboard stats', fakeAsync(() => {
    service.getDashboardStats().subscribe(stats => {
      expect(stats).toBeTruthy();
      expect(stats.totalUsers).toBeGreaterThan(0);
      expect(stats.activeDocuments).toBeGreaterThan(0);
      expect(stats.storageUsed).toBeTruthy();
      expect(stats.activeSessions).toBeGreaterThan(0);
    });
    tick(700);
  }));

  it('should return users list', fakeAsync(() => {
    service.getUsers().subscribe(users => {
      expect(users).toBeTruthy();
      expect(users.length).toBeGreaterThan(0);
      expect(users[0].displayName).toBeTruthy();
      expect(users[0].email).toBeTruthy();
    });
    tick(700);
  }));

  it('should return a single user by id', fakeAsync(() => {
    service.getUser('user-001').subscribe(user => {
      expect(user).toBeTruthy();
      expect(user!.id).toBe('user-001');
    });
    tick(700);
  }));

  it('should return audit events', fakeAsync(() => {
    service.getAuditEvents().subscribe(events => {
      expect(events).toBeTruthy();
      expect(events.length).toBeGreaterThan(0);
      expect(events[0].action).toBeTruthy();
    });
    tick(700);
  }));

  it('should return feature flags', fakeAsync(() => {
    service.getFeatureFlags().subscribe(flags => {
      expect(flags).toBeTruthy();
      expect(flags.length).toBeGreaterThan(0);
      expect(flags[0].name).toBeTruthy();
      expect(flags[0].key).toBeTruthy();
    });
    tick(700);
  }));

  it('should return system health', fakeAsync(() => {
    service.getSystemHealth().subscribe(services => {
      expect(services).toBeTruthy();
      expect(services.length).toBeGreaterThan(0);
      expect(services[0].name).toBeTruthy();
      expect(services[0].status).toBeTruthy();
    });
    tick(700);
  }));

  it('should return announcements', fakeAsync(() => {
    service.getAnnouncements().subscribe(announcements => {
      expect(announcements).toBeTruthy();
      expect(announcements.length).toBeGreaterThan(0);
    });
    tick(700);
  }));

  it('should return analytics report', fakeAsync(() => {
    service.getAnalyticsReport().subscribe(report => {
      expect(report).toBeTruthy();
      expect(report.userSignups).toBeTruthy();
      expect(report.activeUsers).toBeTruthy();
      expect(report.storageUsage).toBeTruthy();
    });
    tick(700);
  }));

  it('should toggle feature flag', fakeAsync(() => {
    service.toggleFeatureFlag('flag-001', true).subscribe(flag => {
      expect(flag).toBeTruthy();
      expect(flag.enabled).toBeTrue();
    });
    tick(700);
  }));

  it('should suspend a user', fakeAsync(() => {
    service.suspendUser('user-001').subscribe(user => {
      expect(user).toBeTruthy();
      expect(user.status).toBe('suspended');
    });
    tick(700);
  }));

  describe('Incident API methods', () => {
    let httpMock: HttpTestingController;

    beforeEach(() => {
      httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => {
      httpMock.verify();
    });

    it('updateIncidentStatus should make a PATCH request', () => {
      const mockResponse = {
        id: 'inc-1', title: 'Test', description: 'Desc', severity: 'high',
        status: 'resolved', affected_service: null, devin_session_id: null,
        devin_session_url: null, devin_session_status: null, reporter_id: null,
        resolved_at: '2026-01-01T00:00:00Z', closed_at: null, active: false,
        created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
      };

      service.updateIncidentStatus('inc-1', 'resolved').subscribe(incident => {
        expect(incident).toBeTruthy();
        expect(incident.status).toBe('resolved');
        expect(incident.id).toBe('inc-1');
      });

      const req = httpMock.expectOne('/api/v1/admin/incidents/inc-1');
      expect(req.request.method).toBe('PATCH');
      expect(req.request.body).toEqual({ incident: { status: 'resolved' } });
      req.flush(mockResponse);
    });

    it('deleteIncident should make a DELETE request', () => {
      service.deleteIncident('inc-1').subscribe();

      const req = httpMock.expectOne('/api/v1/admin/incidents/inc-1');
      expect(req.request.method).toBe('DELETE');
      req.flush(null, { status: 204, statusText: 'No Content' });
    });
  });

  describe('Share policy API methods', () => {
    let httpMock: HttpTestingController;
    const raw = {
      workspace_id: 'default', default_expiry_seconds: 604800, min_expiry_seconds: 3600,
      max_expiry_seconds: 7776000, allow_never: false, updated_by: 'owner-1', updated_at: '2026-11-10T00:00:00Z',
    };

    beforeEach(() => {
      httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => {
      httpMock.verify();
    });

    it('getSharePolicy GETs /documents/share-policy and maps the response', () => {
      service.getSharePolicy().subscribe(p => {
        expect(p).toEqual({
          workspaceId: 'default', defaultExpirySeconds: 604800, minExpirySeconds: 3600,
          maxExpirySeconds: 7776000, allowNever: false, updatedBy: 'owner-1', updatedAt: '2026-11-10T00:00:00Z',
        });
      });
      const req = httpMock.expectOne('/api/v1/documents/share-policy');
      expect(req.request.method).toBe('GET');
      req.flush(raw);
    });

    it('updateSharePolicy PUTs the contract body in snake_case', () => {
      service.updateSharePolicy({
        defaultExpirySeconds: 604800, minExpirySeconds: 3600, maxExpirySeconds: 7776000, allowNever: false,
      }).subscribe(p => expect(p.maxExpirySeconds).toBe(7776000));
      const req = httpMock.expectOne('/api/v1/documents/share-policy');
      expect(req.request.method).toBe('PUT');
      expect(req.request.body).toEqual({
        default_expiry_seconds: 604800, min_expiry_seconds: 3600, max_expiry_seconds: 7776000, allow_never: false,
      });
      req.flush(raw);
    });

    it('updateSharePolicy surfaces a 422 from the API', () => {
      let status = 0;
      service.updateSharePolicy({
        defaultExpirySeconds: 604800, minExpirySeconds: 3600, maxExpirySeconds: 7776000, allowNever: false,
      }).subscribe({ error: err => (status = err.status) });
      httpMock.expectOne('/api/v1/documents/share-policy')
        .flush({ detail: 'invalid' }, { status: 422, statusText: 'Unprocessable Entity' });
      expect(status).toBe(422);
    });

    it('falls back to dev mock defaults while the endpoint is not deployed (404)', fakeAsync(() => {
      let policy: any;
      service.getSharePolicy().subscribe(p => (policy = p));
      httpMock.expectOne('/api/v1/documents/share-policy').flush(null, { status: 404, statusText: 'Not Found' });
      tick(300);
      expect(policy.defaultExpirySeconds).toBe(2592000);
      expect(policy.minExpirySeconds).toBe(3600);
      expect(policy.maxExpirySeconds).toBe(31536000);
      expect(policy.allowNever).toBeFalse();
    }));

    it('dev mock rejects invalid values with a 422', () => {
      let status = 0;
      service.updateSharePolicy({
        defaultExpirySeconds: 3600, minExpirySeconds: 7200, maxExpirySeconds: 86400, allowNever: false,
      }).subscribe({ error: err => (status = err.status) });
      httpMock.expectOne('/api/v1/documents/share-policy').flush(null, { status: 404, statusText: 'Not Found' });
      expect(status).toBe(422);
    });
  });
});
