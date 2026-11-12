import { TestBed } from '@angular/core/testing';
import { HttpClientTestingModule, HttpTestingController } from '@angular/common/http/testing';
import { RouterTestingModule } from '@angular/router/testing';
import { Router } from '@angular/router';
import { AuthService, AuthUser } from './auth.service';
import { futureExp, unsignedJwt } from '../../../testing/jwt';

describe('AuthService', () => {
  let service: AuthService;
  let router: Router;
  let http: HttpTestingController;

  const apiUser = {
    id: 'a0000000-0000-0000-0000-000000000001',
    email: 'admin@otterworks.dev',
    displayName: 'Admin User',
    avatarUrl: null,
  };

  function loginResponse(roles: string[], exp = futureExp()) {
    return {
      accessToken: unsignedJwt({ sub: apiUser.id, roles, exp }),
      refreshToken: 'refresh',
      tokenType: 'Bearer',
      expiresIn: 3600,
      user: apiUser,
    };
  }

  function login(password = 'Admin123!') {
    const result: { user?: AuthUser; error?: Error } = {};
    service.login(apiUser.email, password).subscribe({
      next: user => (result.user = user),
      error: (e: Error) => (result.error = e),
    });
    const req = http.expectOne('/api/v1/auth/login');
    return { req, result };
  }

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

  it('should not be authenticated initially', () => {
    expect(service.isAuthenticated).toBeFalse();
    expect(service.currentUser).toBeNull();
  });

  it('should post credentials to the auth service and store the issued token', () => {
    const response = loginResponse(['ADMIN', 'USER']);
    const { req, result } = login();
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ email: apiUser.email, password: 'Admin123!' });
    req.flush(response);

    expect(result.user).toEqual({
      id: apiUser.id,
      email: apiUser.email,
      displayName: 'Admin User',
      role: 'admin',
    });
    expect(service.isAuthenticated).toBeTrue();
    expect(service.getToken()).toBe(response.accessToken);
    expect(JSON.parse(localStorage.getItem('ow_admin_user')!).email).toBe(apiUser.email);
  });

  it('should map an OWNER token to the owner role', () => {
    const { req, result } = login();
    req.flush(loginResponse(['OWNER']));
    expect(result.user!.role).toBe('owner');
  });

  it('should reject accounts without an admin role and store nothing', () => {
    const { req, result } = login();
    req.flush(loginResponse(['USER']));
    expect(result.error!.message).toBe('This account does not have admin access.');
    expect(service.isAuthenticated).toBeFalse();
    expect(localStorage.getItem('ow_admin_token')).toBeNull();
  });

  it('should surface invalid credentials from the auth service', () => {
    const { req, result } = login('wrong');
    req.flush({ error: 'Invalid credentials' }, { status: 401, statusText: 'Unauthorized' });
    expect(result.error!.message).toBe('Invalid credentials');
    expect(service.isAuthenticated).toBeFalse();
  });

  it('should reject an already-expired access token', () => {
    const { req, result } = login();
    req.flush(loginResponse(['ADMIN'], futureExp(-60)));
    expect(result.error).toBeTruthy();
    expect(service.isAuthenticated).toBeFalse();
  });

  it('should drop an expired stored session', () => {
    localStorage.setItem('ow_admin_token', unsignedJwt({ sub: apiUser.id, roles: ['ADMIN'], exp: futureExp(-60) }));
    localStorage.setItem('ow_admin_user', JSON.stringify(apiUser));
    expect(service.getToken()).toBeNull();
    expect(localStorage.getItem('ow_admin_user')).toBeNull();
  });

  it('should emit the user on currentUser$ and clear state on logout', () => {
    const emitted: (AuthUser | null)[] = [];
    service.currentUser$.subscribe(user => emitted.push(user));
    login().req.flush(loginResponse(['ADMIN']));
    expect(emitted[emitted.length - 1]?.email).toBe(apiUser.email);

    spyOn(router, 'navigate');
    service.logout();
    expect(service.isAuthenticated).toBeFalse();
    expect(service.currentUser).toBeNull();
    expect(localStorage.getItem('ow_admin_token')).toBeNull();
    expect(router.navigate).toHaveBeenCalledWith(['/login']);
  });
});
