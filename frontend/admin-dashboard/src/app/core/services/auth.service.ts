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
  tokenType: string;
  expiresIn: number;
  user: {
    id: string;
    email: string;
    displayName: string;
  };
}

interface TokenClaims {
  roles?: string[];
  role?: string;
}

// Mirrors admin-service's ApplicationController::ADMIN_ROLES; the backend's
// require_admin! check is authoritative, this only keeps non-admins out of the UI.
const ADMIN_ROLES = ['owner', 'super_admin', 'admin'];

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly TOKEN_KEY = 'ow_admin_token';
  private readonly USER_KEY = 'ow_admin_user';
  private readonly LOGIN_URL = '/api/v1/auth/login';
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
    return this.http.post<LoginResponse>(this.LOGIN_URL, { email, password }).pipe(
      catchError((error: HttpErrorResponse) =>
        throwError(() => new Error(error.status === 401 || error.status === 400
          ? 'Invalid credentials'
          : 'Login failed. Please try again.'))
      ),
      map(response => {
        const role = adminRole(response.accessToken);
        if (!role) {
          throw new Error('This account does not have admin access');
        }
        return {
          id: response.user.id,
          email: response.user.email,
          displayName: response.user.displayName,
          role,
          token: response.accessToken,
        };
      }),
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

function adminRole(token: string): string | null {
  const claims = decodeClaims(token);
  if (!claims) {
    return null;
  }
  const roles = (claims.roles?.length ? claims.roles : [claims.role])
    .filter((r): r is string => typeof r === 'string')
    .map(r => r.toLowerCase());
  return ADMIN_ROLES.find(r => roles.includes(r)) ?? null;
}

function decodeClaims(token: string): TokenClaims | null {
  const payload = token?.split('.')[1];
  if (!payload) {
    return null;
  }
  try {
    const base64 = payload.replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(atob(base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), '='))) as TokenClaims;
  } catch {
    return null;
  }
}
