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
    avatarUrl?: string | null;
  };
}

interface TokenClaims {
  sub?: string;
  exp?: number;
  roles?: unknown;
  role?: unknown;
}

// auth-service's top roles; admin-service's require_admin! accepts the same set.
const ADMIN_ROLES = ['owner', 'super_admin', 'admin'];

export const LOGIN_URL = '/api/v1/auth/login';

@Injectable({ providedIn: 'root' })
export class AuthService {
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
    const token = localStorage.getItem(this.TOKEN_KEY);
    if (!token) {
      return null;
    }
    const claims = decodeClaims(token);
    if (!claims || isExpired(claims)) {
      this.clearSession();
      return null;
    }
    return token;
  }

  login(email: string, password: string): Observable<AuthUser> {
    return this.http.post<LoginResponse>(LOGIN_URL, { email, password }).pipe(
      catchError((error: HttpErrorResponse) => throwError(() => new Error(loginErrorMessage(error)))),
      map(response => toAdminUser(response)),
      tap(user => {
        localStorage.setItem(this.TOKEN_KEY, user.token);
        localStorage.setItem(this.USER_KEY, JSON.stringify(user));
        this.currentUserSubject.next(user);
      })
    );
  }

  logout(): void {
    this.clearSession();
    this.router.navigate(['/login']);
  }

  private clearSession(): void {
    localStorage.removeItem(this.TOKEN_KEY);
    localStorage.removeItem(this.USER_KEY);
    if (this.currentUserSubject.value) {
      this.currentUserSubject.next(null);
    }
  }

  private getStoredUser(): AuthUser | null {
    const token = localStorage.getItem(this.TOKEN_KEY);
    const claims = token ? decodeClaims(token) : null;
    if (!claims || isExpired(claims)) {
      return null;
    }
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

function toAdminUser(response: LoginResponse): AuthUser {
  const claims = response?.accessToken ? decodeClaims(response.accessToken) : null;
  if (!claims || isExpired(claims)) {
    throw new Error('Login failed. Please try again.');
  }
  const role = adminRole(claims);
  if (!role) {
    throw new Error('This account does not have admin access.');
  }
  return {
    id: response.user?.id ?? claims.sub ?? '',
    email: response.user?.email ?? '',
    displayName: response.user?.displayName ?? '',
    role,
    token: response.accessToken,
  };
}

function adminRole(claims: TokenClaims): string | null {
  const raw = Array.isArray(claims.roles) ? claims.roles : [claims.role];
  const roles = raw
    .filter((r): r is string => typeof r === 'string')
    .map(r => r.toLowerCase());
  return ADMIN_ROLES.find(r => roles.includes(r)) ?? null;
}

function isExpired(claims: TokenClaims): boolean {
  return typeof claims.exp !== 'number' || claims.exp * 1000 <= Date.now();
}

function decodeClaims(token: string): TokenClaims | null {
  const parts = token.split('.');
  if (parts.length !== 3) {
    return null;
  }
  try {
    const base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    const padded = base64 + '='.repeat((4 - (base64.length % 4)) % 4);
    const claims = JSON.parse(atob(padded));
    return claims && typeof claims === 'object' ? (claims as TokenClaims) : null;
  } catch {
    return null;
  }
}

function loginErrorMessage(error: HttpErrorResponse): string {
  if (error.status === 400 || error.status === 401 || error.status === 403) {
    return 'Invalid email or password.';
  }
  if (error.status === 429) {
    return 'Too many login attempts. Please wait and try again.';
  }
  return 'Login failed. Please try again.';
}
