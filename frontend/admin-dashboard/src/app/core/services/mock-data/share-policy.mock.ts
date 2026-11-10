import { HttpErrorResponse } from '@angular/common/http';
import { Observable, delay, of, throwError } from 'rxjs';
import { SharePolicy, SharePolicyUpdate, validateSharePolicy } from '../../models/share-policy.model';

/** Contract defaults returned by GET /documents/share-policy when no policy has been saved. */
export const DEFAULT_SHARE_POLICY: SharePolicy = {
  workspaceId: 'default',
  defaultExpirySeconds: 2592000,
  minExpirySeconds: 3600,
  maxExpirySeconds: 31536000,
  allowNever: false,
  updatedBy: null,
  updatedAt: null,
};

/**
 * In-memory stand-in for the document-service share policy API, used only in dev
 * builds while the real endpoint is not deployed (it answers 404).
 */
export class MockSharePolicyBackend {
  private policy: SharePolicy = { ...DEFAULT_SHARE_POLICY };

  get(): Observable<SharePolicy> {
    return of({ ...this.policy }).pipe(delay(300));
  }

  put(update: SharePolicyUpdate, actorId: string | null): Observable<SharePolicy> {
    const errors = validateSharePolicy(update);
    if (errors.length) {
      return throwError(() => new HttpErrorResponse({
        status: 422,
        statusText: 'Unprocessable Entity',
        error: { detail: errors.join(' ') },
      }));
    }
    this.policy = { ...this.policy, ...update, updatedBy: actorId, updatedAt: new Date().toISOString() };
    return of({ ...this.policy }).pipe(delay(300));
  }
}
