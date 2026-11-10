import { Injectable, isDevMode } from '@angular/core';
import {
  HttpEvent, HttpHandler, HttpInterceptor, HttpRequest, HttpResponse, HttpErrorResponse,
} from '@angular/common/http';
import { Observable, of, throwError } from 'rxjs';
import { delay } from 'rxjs/operators';
import { SHARE_POLICY_URL } from '../share-policy.service';
import { sharePolicyViolation } from '../../validators/share-policy.validators';

/** Built-in defaults document-service returns until a workspace owner saves a policy. */
export const MOCK_SHARE_POLICY_RESPONSE = {
  workspace_id: 'default',
  default_expiry_days: 7,
  min_expiry_days: 1,
  max_expiry_days: 30,
  updated_by: null as string | null,
  updated_at: null as string | null,
};

/** localStorage switch that turns on the share-policy mock in `ng serve` (dev mode only). */
export const SHARE_POLICY_MOCK_STORAGE_KEY = 'ow_mock_share_policy';

/**
 * In-memory stand-in for document-service GET/PUT /api/v1/documents/share-policy,
 * returning the same shapes and 422 rules as the real API. Only active in dev mode
 * when localStorage[SHARE_POLICY_MOCK_STORAGE_KEY] === 'true'.
 */
@Injectable()
export class SharePolicyMockInterceptor implements HttpInterceptor {
  private policy = { ...MOCK_SHARE_POLICY_RESPONSE };

  static isEnabled(): boolean {
    return isDevMode() && localStorage.getItem(SHARE_POLICY_MOCK_STORAGE_KEY) === 'true';
  }

  intercept(req: HttpRequest<unknown>, next: HttpHandler): Observable<HttpEvent<unknown>> {
    if (!req.url.endsWith(SHARE_POLICY_URL) || !SharePolicyMockInterceptor.isEnabled()) {
      return next.handle(req);
    }
    if (req.method === 'GET') {
      return of(new HttpResponse({ status: 200, body: { ...this.policy } })).pipe(delay(300));
    }
    if (req.method === 'PUT') {
      const body = (req.body ?? {}) as Record<string, number>;
      const update = {
        defaultExpiryDays: body['default_expiry_days'],
        minExpiryDays: body['min_expiry_days'],
        maxExpiryDays: body['max_expiry_days'],
      };
      const violation = sharePolicyViolation(update);
      if (violation) {
        return throwError(() => new HttpErrorResponse({
          status: 422, statusText: 'Unprocessable Entity', url: req.url, error: { detail: violation },
        }));
      }
      this.policy = {
        ...this.policy,
        default_expiry_days: update.defaultExpiryDays,
        min_expiry_days: update.minExpiryDays,
        max_expiry_days: update.maxExpiryDays,
        updated_by: 'a0000000-0000-0000-0000-000000000001',
        updated_at: new Date().toISOString(),
      };
      return of(new HttpResponse({ status: 200, body: { ...this.policy } })).pipe(delay(300));
    }
    return next.handle(req);
  }
}
