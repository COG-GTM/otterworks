import { TestBed, fakeAsync, tick } from '@angular/core/testing';
import { HttpClientTestingModule, HttpTestingController } from '@angular/common/http/testing';
import { HttpErrorResponse, HttpHandler, HttpRequest, HttpResponse } from '@angular/common/http';
import { RouterTestingModule } from '@angular/router/testing';
import { Router } from '@angular/router';
import { of, throwError } from 'rxjs';
import { AdminApiService } from './admin-api.service';
import { AuthService } from './auth.service';
import { JwtInterceptor } from '../interceptors/jwt.interceptor';

// QA admin-audit unit layer. Findings QA-AA-N are documented in docs/qa/admin-audit.md.
describe('QA admin-audit: AdminApiService contract', () => {
  let api: AdminApiService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [HttpClientTestingModule] });
    api = TestBed.inject(AdminApiService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('maps backend users (snake_case + quota) to the UI model', () => {
    let users: any[] = [];
    api.getUsers().subscribe(u => (users = u));
    http.expectOne('/api/v1/admin/users').flush({
      users: [{
        id: 'u1', email: 'a@b.c', display_name: 'Ada', role: 'editor', status: 'suspended',
        created_at: '2026-01-01T00:00:00Z', metadata: { department: 'Eng' },
        storage_quota: { used_bytes: 10, quota_bytes: 100 },
      }],
    });
    expect(users[0]).toEqual(jasmine.objectContaining({
      id: 'u1', displayName: 'Ada', role: 'editor', status: 'suspended',
      department: 'Eng', storageUsed: 10, storageQuota: 100, lastLogin: '2026-01-01T00:00:00Z',
    }));
  });

  it('suspend calls PUT /users/:id/suspend', () => {
    api.suspendUser('u1').subscribe();
    const req = http.expectOne('/api/v1/admin/users/u1/suspend');
    expect(req.request.method).toBe('PUT');
    req.flush({ id: 'u1', status: 'suspended' });
  });

  it('restore calls PUT /users/:id/activate', () => {
    let status = '';
    api.restoreUser('u1').subscribe(u => (status = u.status));
    const req = http.expectOne('/api/v1/admin/users/u1/activate');
    expect(req.request.method).toBe('PUT');
    req.flush({ id: 'u1', status: 'active' });
    expect(status).toBe('active');
  });

  it('delete calls DELETE /users/:id', () => {
    api.deleteUser('u1').subscribe();
    expect(http.expectOne('/api/v1/admin/users/u1').request.method).toBe('DELETE');
  });

  it('maps audit logs with actor email, server timestamp and normalized action', () => {
    let events: any[] = [];
    api.getAuditEvents().subscribe(e => (events = e));
    http.expectOne('/api/v1/admin/audit-logs').flush({
      audit_logs: [
        { id: '1', action: 'user.suspended', actor_id: 'a1', actor_email: 'qa@x.io', resource_type: 'AdminUser',
          resource_id: 'u1', created_at: '2026-10-23T10:00:00Z', changes_made: { reason: 'r' }, ip_address: '1.2.3.4' },
        { id: '2', action: 'user.activated', actor_id: 'a1', created_at: '2026-10-23T10:01:00Z' },
        { id: '3', action: 'user.updated', created_at: '2026-10-23T10:02:00Z' },
      ],
    });
    expect(events[0]).toEqual(jasmine.objectContaining({
      action: 'suspend', userId: 'a1', userName: 'qa@x.io', timestamp: '2026-10-23T10:00:00Z',
      resourceType: 'AdminUser', resourceName: 'u1', ipAddress: '1.2.3.4',
    }));
    expect(events[0].details).toContain('reason');
    expect(events[1].action).toBe('restore');
    expect(events[1].userName).toBe('a1');
    expect(events[2].action).toBe('update');
    expect(events[2].userName).toBe('System');
  });

  it('tolerates an empty audit response', () => {
    let events: any[] | undefined;
    api.getAuditEvents().subscribe(e => (events = e));
    http.expectOne('/api/v1/admin/audit-logs').flush({});
    expect(events).toEqual([]);
  });

  it('user-detail activity should include actions performed ON the user (QA-AA-8)', () => {
    pending('QA-AA-8: getUserActivity queries actor_id (actions BY the user) so admin actions on the user never show');
    api.getUserActivity('u1').subscribe();
    http.expectOne(r => r.url.includes('resource_id=u1'));
  });
});

describe('QA admin-audit: AuthService', () => {
  let auth: AuthService;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({ imports: [HttpClientTestingModule, RouterTestingModule] });
    auth = TestBed.inject(AuthService);
    spyOn(TestBed.inject(Router), 'navigate').and.resolveTo(true);
  });

  afterEach(() => localStorage.clear());

  it('rejects an empty password', fakeAsync(() => {
    let failed = false;
    auth.login('a@b.c', '').subscribe({ error: () => (failed = true) });
    tick(1000);
    expect(failed).toBeTrue();
    expect(auth.isAuthenticated).toBeFalse();
  }));

  it('stores the token on login and clears it on logout', fakeAsync(() => {
    auth.login('admin@otterworks.io', 'pw').subscribe();
    tick(1000);
    expect(auth.getToken()).toBeTruthy();
    auth.logout();
    expect(auth.getToken()).toBeNull();
    expect(auth.currentUser).toBeNull();
  }));

  it('authenticates against the backend instead of accepting any credentials (QA-AA-1)', () => {
    pending('QA-AA-1: login() uses mockLogin; any email/password yields a hard-coded admin JWT, no HTTP call');
    const http = TestBed.inject(HttpTestingController);
    auth.login('nobody@evil.io', 'wrong').subscribe();
    http.expectOne(r => r.method === 'POST' && r.url.includes('/auth/login'));
  });
});

describe('QA admin-audit: JwtInterceptor', () => {
  let auth: jasmine.SpyObj<AuthService>;
  let interceptor: JwtInterceptor;

  beforeEach(() => {
    auth = jasmine.createSpyObj<AuthService>('AuthService', ['getToken', 'logout']);
    interceptor = new JwtInterceptor(auth);
  });

  it('adds the bearer token when present', () => {
    auth.getToken.and.returnValue('tok');
    let sent: HttpRequest<unknown> | undefined;
    const next: HttpHandler = { handle: r => { sent = r; return of(new HttpResponse()); } };
    interceptor.intercept(new HttpRequest('GET', '/api/v1/admin/users'), next).subscribe();
    expect(sent!.headers.get('Authorization')).toBe('Bearer tok');
  });

  it('sends no Authorization header without a token', () => {
    auth.getToken.and.returnValue(null);
    let sent: HttpRequest<unknown> | undefined;
    const next: HttpHandler = { handle: r => { sent = r; return of(new HttpResponse()); } };
    interceptor.intercept(new HttpRequest('GET', '/x'), next).subscribe();
    expect(sent!.headers.has('Authorization')).toBeFalse();
  });

  it('logs out on 401 and rethrows', () => {
    auth.getToken.and.returnValue('tok');
    const next: HttpHandler = { handle: () => throwError(() => new HttpErrorResponse({ status: 401 })) };
    let status = 0;
    interceptor.intercept(new HttpRequest('GET', '/x'), next).subscribe({ error: e => (status = e.status) });
    expect(auth.logout).toHaveBeenCalled();
    expect(status).toBe(401);
  });

  it('does not log out on 403', () => {
    auth.getToken.and.returnValue('tok');
    const next: HttpHandler = { handle: () => throwError(() => new HttpErrorResponse({ status: 403 })) };
    interceptor.intercept(new HttpRequest('GET', '/x'), next).subscribe({ error: () => undefined });
    expect(auth.logout).not.toHaveBeenCalled();
  });
});
