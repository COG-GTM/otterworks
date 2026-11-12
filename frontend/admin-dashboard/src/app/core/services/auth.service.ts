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
}

interface LoginResponse {
  accessToken: string;
  refreshToken?: string;
  tokenType?: string;
  expiresIn?: number;
  user: {
    id: string;
    email: string;
    displayName: string;
    avatarUrl?: string | null;
  };
}

interface TokenClaims {
  sub?: string;
  roles?: string[];
  exp?: number;
}

const ADMIN_ROLES = ['OWNER', 'ADMIN'];

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly loginUrl = '/api/v1/auth/login';
  private readonly tokenStorageKey = 'ow_admin_token';
  private readonly userStorageKey = 'ow_admin_user';
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
    const token = localStorage.getItem(this.tokenStorageKey);
    if (!token) {
      return null;
    }
    const claims = decodeClaims(token);
    if (!claims || isExpired(claims)) {
      this.logout();
      return null;
    }
    return token;
  }

  login(email: string, password: string): Observable<AuthUser> {
    return this.http.post<LoginResponse>(this.loginUrl, { email, password }).pipe(
      catchError((error: HttpErrorResponse) => throwError(() => new Error(loginErrorMessage(error)))),
      map(response => {
        const claims = response?.accessToken ? decodeClaims(response.accessToken) : null;
        if (!claims || isExpired(claims)) {
          throw new Error('Login failed. Please try again.');
        }
        const role = ADMIN_ROLES.find(r => claims.roles?.includes(r));
        if (!role) {
          throw new Error('This account does not have admin access.');
        }
        const user: AuthUser = {
          id: response.user.id,
          email: response.user.email,
          displayName: response.user.displayName,
          role: role.toLowerCase(),
        };
        return { user, token: response.accessToken };
      }),
      tap(({ user, token }) => {
        localStorage.setItem(this.tokenStorageKey, token);
        localStorage.setItem(this.userStorageKey, JSON.stringify(user));
        this.currentUserSubject.next(user);
      }),
      map(({ user }) => user)
    );
  }

  logout(): void {
    this.clearSession();
    this.router.navigate(['/login']);
  }

  private clearSession(): void {
    localStorage.removeItem(this.tokenStorageKey);
    localStorage.removeItem(this.userStorageKey);
    this.currentUserSubject.next(null);
  }

  private getStoredUser(): AuthUser | null {
    const stored = localStorage.getItem(this.userStorageKey);
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

function decodeClaims(token: string): TokenClaims | null {
  const parts = token.split('.');
  if (parts.length !== 3) {
    return null;
  }
  try {
    const base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    const padded = base64 + '='.repeat((4 - (base64.length % 4)) % 4);
    return JSON.parse(atob(padded)) as TokenClaims;
  } catch {
    return null;
  }
}

function isExpired(claims: TokenClaims): boolean {
  return typeof claims.exp === 'number' && claims.exp * 1000 <= Date.now();
}

function loginErrorMessage(error: HttpErrorResponse): string {
  if (error.status === 400 || error.status === 401 || error.status === 403) {
    return 'Invalid credentials';
  }
  if (error.status === 429) {
    return 'Too many login attempts. Please try again later.';
  }
  return 'Login failed. Please try again.';
}
