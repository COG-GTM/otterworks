import { TestBed } from '@angular/core/testing';
import { HttpClientTestingModule, HttpTestingController } from '@angular/common/http/testing';
import { RouterTestingModule } from '@angular/router/testing';
import { Router } from '@angular/router';
import { AuthService, AuthUser, LOGIN_URL } from './auth.service';

function base64Url(value: object): string {
  return btoa(JSON.stringify(value)).replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_');
}

function makeToken(claims: object): string {
  return `${base64Url({ alg: 'HS512', typ: 'JWT' })}.${base64Url(claims)}.signature`;
}

const inOneHour = () => Math.floor(Date.now() / 1000) + 3600;

function loginResponse(token: string) {
  return {
    accessToken: token,
    refreshToken: 'refresh',
    tokenType: 'Bearer',
    expiresIn: 3600,
    user: { id: 'u-1', email: 'admin@otterworks.dev', displayName: 'Admin User', avatarUrl: null },
  };
}

describe('AuthService', () => {
  let service: AuthService;
  let router: Router;
  let http: HttpTestingController;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule, RouterTestingModule],
    });
    service = TestBed.inject(AuthService);
    router = TestBed.inject(Router);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    localStorage.clear();
  });

  function login(email = 'admin@otterworks.dev', password = 'Admin123!') {
    const result: { user?: AuthUser; error?: Error } = {};
    service.login(email, password).subscribe({
      next: user => (result.user = user),
      error: (e: Error) => (result.error = e),
    });
    const req = http.expectOne(LOGIN_URL);
    return { req, result };
  }

  it('should not be authenticated initially', () => {
    expect(service.isAuthenticated).toBeFalse();
    expect(service.currentUser).toBeNull();
  });

  it('sends the credentials to auth-service and stores the issued token', () => {
    const token = makeToken({ sub: 'u-1', roles: ['USER', 'ADMIN'], exp: inOneHour() });
    const { req, result } = login();
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ email: 'admin@otterworks.dev', password: 'Admin123!' });
    req.flush(loginResponse(token));

    expect(result.user!.role).toBe('admin');
    expect(result.user!.id).toBe('u-1');
    expect(service.getToken()).toBe(token);
    expect(service.isAuthenticated).toBeTrue();
    expect(service.currentUser!.email).toBe('admin@otterworks.dev');
    expect(JSON.parse(localStorage.getItem('ow_admin_user')!).token).toBe(token);
  });

  it('picks the highest admin role from the token', () => {
    const { req, result } = login();
    req.flush(loginResponse(makeToken({ sub: 'u-1', roles: ['ADMIN', 'OWNER'], exp: inOneHour() })));
    expect(result.user!.role).toBe('owner');
  });

  it('rejects wrong credentials without storing anything', () => {
    const { req, result } = login('admin@otterworks.dev', 'wrong');
    req.flush({ error: 'Invalid credentials' }, { status: 400, statusText: 'Bad Request' });
    expect(result.error!.message).toBe('Invalid email or password.');
    expect(service.isAuthenticated).toBeFalse();
    expect(localStorage.getItem('ow_admin_token')).toBeNull();
  });

  it('rejects a valid login for an account without an admin role', () => {
    const { req, result } = login('user@otterworks.dev', 'pw');
    req.flush(loginResponse(makeToken({ sub: 'u-2', roles: ['USER', 'EDITOR'], exp: inOneHour() })));
    expect(result.error!.message).toBe('This account does not have admin access.');
    expect(service.isAuthenticated).toBeFalse();
    expect(localStorage.getItem('ow_admin_token')).toBeNull();
  });

  it('rejects an already-expired token from the server', () => {
    const { req, result } = login();
    req.flush(loginResponse(makeToken({ sub: 'u-1', roles: ['ADMIN'], exp: 1 })));
    expect(result.error).toBeTruthy();
    expect(service.isAuthenticated).toBeFalse();
  });

  it('does not ship a built-in token: nothing is stored until the server answers', () => {
    service.login('anyone@example.com', 'x').subscribe({ error: () => undefined });
    expect(localStorage.getItem('ow_admin_token')).toBeNull();
    http.expectOne(LOGIN_URL).flush({}, { status: 401, statusText: 'Unauthorized' });
    expect(localStorage.getItem('ow_admin_token')).toBeNull();
  });

  it('treats an expired stored token as signed out', () => {
    localStorage.setItem('ow_admin_token', makeToken({ sub: 'u-1', roles: ['ADMIN'], exp: 1 }));
    expect(service.getToken()).toBeNull();
    expect(service.isAuthenticated).toBeFalse();
    expect(localStorage.getItem('ow_admin_token')).toBeNull();
  });

  it('treats a malformed stored token as signed out', () => {
    localStorage.setItem('ow_admin_token', 'mock-jwt-token-123');
    expect(service.isAuthenticated).toBeFalse();
  });

  it('should clear auth state on logout', () => {
    const { req } = login();
    req.flush(loginResponse(makeToken({ sub: 'u-1', roles: ['ADMIN'], exp: inOneHour() })));
    spyOn(router, 'navigate');
    service.logout();
    expect(service.isAuthenticated).toBeFalse();
    expect(service.currentUser).toBeNull();
    expect(localStorage.getItem('ow_admin_token')).toBeNull();
    expect(router.navigate).toHaveBeenCalledWith(['/login']);
  });

  it('should emit user on currentUser$ observable', () => {
    const emitted: (AuthUser | null)[] = [];
    service.currentUser$.subscribe(user => emitted.push(user));
    const { req } = login();
    req.flush(loginResponse(makeToken({ sub: 'u-1', roles: ['ADMIN'], exp: inOneHour() })));
    expect(emitted.length).toBeGreaterThanOrEqual(2);
    expect(emitted[emitted.length - 1]!.role).toBe('admin');
  });
});
