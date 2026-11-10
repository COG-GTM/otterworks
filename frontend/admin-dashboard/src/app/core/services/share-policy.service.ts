import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, map } from 'rxjs';
import { SharePolicy, SharePolicyUpdate } from '../models/share-policy.model';

export const SHARE_POLICY_URL = '/api/v1/documents/share-policy';

interface SharePolicyResponse {
  workspace_id: string;
  default_expiry_days: number;
  min_expiry_days: number;
  max_expiry_days: number;
  updated_by: string | null;
  updated_at: string | null;
}

@Injectable({ providedIn: 'root' })
export class SharePolicyService {
  constructor(private http: HttpClient) {}

  getPolicy(): Observable<SharePolicy> {
    return this.http.get<SharePolicyResponse>(SHARE_POLICY_URL).pipe(map(res => this.mapPolicy(res)));
  }

  updatePolicy(update: SharePolicyUpdate): Observable<SharePolicy> {
    return this.http.put<SharePolicyResponse>(SHARE_POLICY_URL, {
      default_expiry_days: update.defaultExpiryDays,
      min_expiry_days: update.minExpiryDays,
      max_expiry_days: update.maxExpiryDays,
    }).pipe(map(res => this.mapPolicy(res)));
  }

  private mapPolicy(raw: SharePolicyResponse): SharePolicy {
    return {
      workspaceId: raw.workspace_id,
      defaultExpiryDays: raw.default_expiry_days,
      minExpiryDays: raw.min_expiry_days,
      maxExpiryDays: raw.max_expiry_days,
      updatedBy: raw.updated_by ?? null,
      updatedAt: raw.updated_at ?? null,
    };
  }
}
