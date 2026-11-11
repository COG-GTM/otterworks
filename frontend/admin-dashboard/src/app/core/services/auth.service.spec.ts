import { TestBed } from '@angular/core/testing';
import { HttpClientTestingModule, HttpTestingController } from '@angular/common/http/testing';
import { RouterTestingModule } from '@angular/router/testing';
import { Router } from '@angular/router';
import { AuthService, AuthUser } from './auth.service';

function base64Url(value: object): string {
  return btoa(JSON.stringify(value)).replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_');
}

function token(claims: object): string {
  return `${base64Url({ alg: 'HS512' })}.${base64Url(claims)}.signature`;
}

function loginResponse(accessToken: string) {
  return {
    accessToken,
    refreshToken: 'refresh',
    tokenType: 'Bearer',
    expiresIn: 3600,
    user: { id: 'u-1', email: 'admin@otterworks.dev', displayName: 'Admin User' },
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
    const req = http.expectOne('/api/v1/auth/login');
    return { req, result };
  }

  it('should not be authenticated initially', () => {
    expect(service.isAuthenticated).toBeFalse();
    expect(service.currentUser).toBeNull();
  });

  it('should send the credentials to auth-service', () => {
    const { req } = login('admin@otterworks.dev', 'Admin123!');
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ email: 'admin@otterworks.dev', password: 'Admin123!' });
    req.flush(loginResponse(token({ roles: ['ADMIN', 'USER'] })));
  });

  it('should store the token issued by the backend for an admin account', () => {
    const issued = token({ sub: 'u-1', roles: ['USER', 'ADMIN'] });
    const { req, result } = login();
    req.flush(loginResponse(issued));

    expect(result.user!.role).toBe('admin');
    expect(result.user!.email).toBe('admin@otterworks.dev');
    expect(service.getToken()).toBe(issued);
    expect(service.isAuthenticated).toBeTrue();
    expect(JSON.parse(localStorage.getItem('ow_admin_user')!).id).toBe('u-1');
  });

  it('should pick the highest admin role from the token', () => {
    const { req, result } = login();
    req.flush(loginResponse(token({ roles: ['ADMIN', 'OWNER'] })));
    expect(result.user!.role).toBe('owner');
  });

  it('should reject an account without an admin role', () => {
    const { req, result } = login();
    req.flush(loginResponse(token({ roles: ['USER', 'EDITOR'] })));

    expect(result.error!.message).toBe('This account does not have admin access');
    expect(service.getToken()).toBeNull();
    expect(service.isAuthenticated).toBeFalse();
  });

  it('should reject a malformed token', () => {
    const { req, result } = login();
    req.flush(loginResponse('not-a-jwt'));
    expect(result.error).toBeTruthy();
    expect(service.getToken()).toBeNull();
  });

  it('should report invalid credentials when auth-service refuses the login', () => {
    const { req, result } = login('admin@otterworks.dev', 'wrong');
    req.flush({ error: 'Invalid email or password' }, { status: 401, statusText: 'Unauthorized' });

    expect(result.error!.message).toBe('Invalid credentials');
    expect(service.getToken()).toBeNull();
  });

  it('should emit the user on currentUser$', () => {
    const emitted: (AuthUser | null)[] = [];
    service.currentUser$.subscribe(user => emitted.push(user));
    const { req } = login();
    req.flush(loginResponse(token({ roles: ['ADMIN'] })));
    expect(emitted[emitted.length - 1]!.role).toBe('admin');
  });

  it('should clear auth state on logout', () => {
    const { req } = login();
    req.flush(loginResponse(token({ roles: ['ADMIN'] })));
    spyOn(router, 'navigate');

    service.logout();

    expect(service.isAuthenticated).toBeFalse();
    expect(service.currentUser).toBeNull();
    expect(localStorage.getItem('ow_admin_token')).toBeNull();
    expect(router.navigate).toHaveBeenCalledWith(['/login']);
  });
});
