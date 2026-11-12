import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { RouterTestingModule } from '@angular/router/testing';
import { HttpClientTestingModule } from '@angular/common/http/testing';
import { ActivatedRouteSnapshot, RouterStateSnapshot } from '@angular/router';
import { authGuard } from './auth.guard';
import { AuthService } from '../services/auth.service';
import { futureExp, unsignedJwt } from '../../../testing/jwt';

describe('authGuard', () => {
  let authService: AuthService;
  let router: Router;
  const mockRoute = {} as ActivatedRouteSnapshot;
  const mockState = { url: '/dashboard' } as RouterStateSnapshot;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule, RouterTestingModule],
    });
    authService = TestBed.inject(AuthService);
    router = TestBed.inject(Router);
  });

  afterEach(() => {
    localStorage.clear();
  });

  it('should deny access when not authenticated', () => {
    spyOn(router, 'navigate');
    const result = TestBed.runInInjectionContext(() => authGuard(mockRoute, mockState));
    expect(result).toBeFalse();
    expect(router.navigate).toHaveBeenCalledWith(['/login']);
  });

  it('should allow access when authenticated', () => {
    localStorage.setItem('ow_admin_token', unsignedJwt({ sub: 'u1', roles: ['ADMIN'], exp: futureExp() }));
    const result = TestBed.runInInjectionContext(() => authGuard(mockRoute, mockState));
    expect(result).toBeTrue();
  });

  it('should deny access when the stored session has expired', () => {
    spyOn(router, 'navigate');
    localStorage.setItem('ow_admin_token', unsignedJwt({ sub: 'u1', roles: ['ADMIN'], exp: futureExp(-60) }));
    const result = TestBed.runInInjectionContext(() => authGuard(mockRoute, mockState));
    expect(result).toBeFalse();
    expect(localStorage.getItem('ow_admin_token')).toBeNull();
  });
});
