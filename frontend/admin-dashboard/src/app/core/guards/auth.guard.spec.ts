import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { RouterTestingModule } from '@angular/router/testing';
import { HttpClientTestingModule } from '@angular/common/http/testing';
import { ActivatedRouteSnapshot, RouterStateSnapshot } from '@angular/router';
import { authGuard } from './auth.guard';
import { AuthService } from '../services/auth.service';

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
    const claims = btoa(JSON.stringify({ sub: 'u-1', roles: ['ADMIN'], exp: Math.floor(Date.now() / 1000) + 3600 }));
    localStorage.setItem('ow_admin_token', `header.${claims.replace(/=+$/, '')}.sig`);
    const result = TestBed.runInInjectionContext(() => authGuard(mockRoute, mockState));
    expect(result).toBeTrue();
  });

  it('should deny access when the stored token has expired', () => {
    spyOn(router, 'navigate');
    const claims = btoa(JSON.stringify({ sub: 'u-1', roles: ['ADMIN'], exp: 1 }));
    localStorage.setItem('ow_admin_token', `header.${claims.replace(/=+$/, '')}.sig`);
    const result = TestBed.runInInjectionContext(() => authGuard(mockRoute, mockState));
    expect(result).toBeFalse();
    expect(router.navigate).toHaveBeenCalledWith(['/login']);
  });
});
