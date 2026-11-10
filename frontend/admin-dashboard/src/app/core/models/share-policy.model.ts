export interface SharePolicy {
  workspaceId: string;
  defaultExpiryDays: number;
  minExpiryDays: number;
  maxExpiryDays: number;
  updatedBy: string | null;
  updatedAt: string | null;
}

export interface SharePolicyUpdate {
  defaultExpiryDays: number;
  minExpiryDays: number;
  maxExpiryDays: number;
}

/** Hard limits enforced by document-service (PUT /documents/share-policy returns 422 outside them). */
export const SHARE_POLICY_LIMITS = {
  floorDays: 1,
  ceilingDays: 365,
} as const;
