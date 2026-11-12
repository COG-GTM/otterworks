import { TestBed } from '@angular/core/testing';
import { HttpClientTestingModule, HttpTestingController } from '@angular/common/http/testing';
import { RouterTestingModule } from '@angular/router/testing';
import { Router } from '@angular/router';
import { AuthService, AuthUser } from './auth.service';

function base64Url(value: object): string {
  return btoa(JSON.stringify(value)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function fakeAccessToken(claims: object): string {
  return `${base64Url({ alg: 'HS512', typ: 'JWT' })}.${base64Url(claims)}.signature`;
}

function loginResponse(roles: string[]) {
  return {
    accessToken: fakeAccessToken({ sub: 'user-1', email: 'admin@otterworks.dev', roles, type: 'access' }),
    refreshToken: 'refresh-token',
    tokenType: 'Bearer',
    expiresIn: 3600,
    user: { id: 'user-1', email: 'admin@otterworks.dev', displayName: 'Admin User', avatarUrl: null },
  };
}

describe('AuthService', () => {
  let service: AuthService;
  let router: Router;
  let httpMock: HttpTestingController;

  function login(roles = ['USER', 'ADMIN']): { user?: AuthUser; error?: Error } {
    const result: { user?: AuthUser; error?: Error } = {};
    service.login('admin@otterworks.dev', 'Admin123!').subscribe({
      next: user => { result.user = user; },
      error: (e: Error) => { result.error = e; },
    });
    const req = httpMock.expectOne('/api/v1/auth/login');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ email: 'admin@otterworks.dev', password: 'Admin123!' });
    req.flush(loginResponse(roles));
    return result;
  }

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule, RouterTestingModule],
    });
    service = TestBed.inject(AuthService);
    router = TestBed.inject(Router);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
    localStorage.clear();
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('should not be authenticated initially', () => {
    expect(service.isAuthenticated).toBeFalse();
    expect(service.currentUser).toBeNull();
  });

  it('should login via the auth API and use the server-issued token', () => {
    const { user } = login();
    expect(user).toBeTruthy();
    expect(user!.email).toBe('admin@otterworks.dev');
    expect(user!.role).toBe('admin');
    expect(user!.token).toBe(loginResponse(['USER', 'ADMIN']).accessToken);
    expect(service.isAuthenticated).toBeTrue();
    expect(service.getToken()).toBe(user!.token);
    expect(localStorage.getItem('ow_admin_user')).toBeTruthy();
  });

  it('should pick the highest-privilege role', () => {
    expect(login(['USER', 'OWNER', 'ADMIN']).user!.role).toBe('owner');
  });

  it('should reject users without an admin role', () => {
    const { user, error } = login(['USER', 'EDITOR']);
    expect(user).toBeUndefined();
    expect(error!.message).toBe('Admin role required');
    expect(service.isAuthenticated).toBeFalse();
  });

  it('should map auth API 401 to invalid credentials', () => {
    let error: Error | undefined;
    service.login('admin@otterworks.dev', 'wrong').subscribe({ error: (e: Error) => { error = e; } });
    httpMock.expectOne('/api/v1/auth/login').flush({ error: 'Invalid credentials' }, { status: 401, statusText: 'Unauthorized' });
    expect(error!.message).toBe('Invalid credentials');
    expect(service.isAuthenticated).toBeFalse();
  });

  it('should reject login with empty password without calling the API', () => {
    let error: Error | undefined;
    service.login('admin@otterworks.dev', '').subscribe({ error: (e: Error) => { error = e; } });
    httpMock.expectNone('/api/v1/auth/login');
    expect(error!.message).toBe('Invalid credentials');
  });

  it('should emit user on currentUser$ observable', () => {
    const emitted: (AuthUser | null)[] = [];
    service.currentUser$.subscribe(user => emitted.push(user));
    login();
    expect(emitted.length).toBeGreaterThanOrEqual(2);
    expect(emitted[emitted.length - 1]).toBeTruthy();
  });

  it('should clear auth state on logout', () => {
    login();
    spyOn(router, 'navigate');
    service.logout();
    expect(service.isAuthenticated).toBeFalse();
    expect(service.currentUser).toBeNull();
    expect(localStorage.getItem('ow_admin_token')).toBeNull();
    expect(router.navigate).toHaveBeenCalledWith(['/login']);
  });
});
