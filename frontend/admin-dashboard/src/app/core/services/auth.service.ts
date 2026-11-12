import { Injectable } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { BehaviorSubject, Observable, throwError } from 'rxjs';
import { catchError, map, tap } from 'rxjs/operators';
import { Router } from '@angular/router';

export interface AuthUser {
  id: string;
  email: string;
  displayName: string;
  role: string;
  token: string;
}

interface LoginResponse {
  accessToken: string;
  refreshToken: string;
  tokenType: string;
  expiresIn: number;
  user: {
    id: string;
    email: string;
    displayName: string;
    avatarUrl: string | null;
  };
}

interface AccessTokenClaims {
  roles?: string[];
  role?: string;
}

// Mirrors admin-service's JwtAuthenticator role precedence and ADMIN_ROLES.
const ROLE_PRECEDENCE = ['owner', 'super_admin', 'admin', 'editor', 'viewer', 'user'];
const ADMIN_ROLES = ['owner', 'super_admin', 'admin'];

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly LOGIN_URL = '/api/v1/auth/login';
  private readonly TOKEN_KEY = 'ow_admin_token';
  private readonly USER_KEY = 'ow_admin_user';
  private currentUserSubject = new BehaviorSubject<AuthUser | null>(this.getStoredUser());
  currentUser$ = this.currentUserSubject.asObservable();

  constructor(private http: HttpClient, private router: Router) {}

  get isAuthenticated(): boolean {
    return !!this.getToken();
  }

  get currentUser(): AuthUser | null {
    return this.currentUserSubject.value;
  }

  getToken(): string | null {
    return localStorage.getItem(this.TOKEN_KEY);
  }

  login(email: string, password: string): Observable<AuthUser> {
    if (!email || !password) {
      return throwError(() => new Error('Invalid credentials'));
    }
    return this.http.post<LoginResponse>(this.LOGIN_URL, { email, password }).pipe(
      catchError((error: HttpErrorResponse) =>
        throwError(() => new Error(error.status === 401 || error.status === 400
          ? 'Invalid credentials'
          : 'Unable to sign in. Please try again later.'))
      ),
      map(response => this.toAuthUser(response)),
      tap(user => {
        localStorage.setItem(this.TOKEN_KEY, user.token);
        localStorage.setItem(this.USER_KEY, JSON.stringify(user));
        this.currentUserSubject.next(user);
      })
    );
  }

  logout(): void {
    localStorage.removeItem(this.TOKEN_KEY);
    localStorage.removeItem(this.USER_KEY);
    this.currentUserSubject.next(null);
    this.router.navigate(['/login']);
  }

  private toAuthUser(response: LoginResponse): AuthUser {
    const role = this.extractRole(response.accessToken);
    if (!role || !ADMIN_ROLES.includes(role)) {
      throw new Error('Admin role required');
    }
    return {
      id: response.user.id,
      email: response.user.email,
      displayName: response.user.displayName,
      role,
      token: response.accessToken,
    };
  }

  // Reads (does not verify) the role claim for display/gating only; the
  // backend verifies the signature and enforces authorization.
  private extractRole(token: string): string | null {
    const claims = this.decodeClaims(token);
    if (!claims) {
      return null;
    }
    const raw = claims.roles?.length ? claims.roles : [claims.role];
    const roles = raw.filter((r): r is string => !!r).map(r => r.toLowerCase());
    return ROLE_PRECEDENCE.find(r => roles.includes(r)) ?? roles[0] ?? null;
  }

  private decodeClaims(token: string): AccessTokenClaims | null {
    const payload = token.split('.')[1];
    if (!payload) {
      return null;
    }
    try {
      const base64 = payload.replace(/-/g, '+').replace(/_/g, '/');
      const padded = base64 + '='.repeat((4 - (base64.length % 4)) % 4);
      return JSON.parse(atob(padded)) as AccessTokenClaims;
    } catch {
      return null;
    }
  }

  private getStoredUser(): AuthUser | null {
    const stored = localStorage.getItem(this.USER_KEY);
    if (stored) {
      try {
        return JSON.parse(stored) as AuthUser;
      } catch {
        return null;
      }
    }
    return null;
  }
}
