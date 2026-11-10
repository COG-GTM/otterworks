export interface SharePolicy {
  workspaceId: string;
  defaultExpirySeconds: number;
  minExpirySeconds: number;
  maxExpirySeconds: number;
  allowNever: boolean;
  updatedBy: string | null;
  updatedAt: string | null;
}

export type SharePolicyUpdate = Pick<
  SharePolicy,
  'defaultExpirySeconds' | 'minExpirySeconds' | 'maxExpirySeconds' | 'allowNever'
>;

export const HOUR_SECONDS = 3600;
export const DAY_SECONDS = 86400;
export const MAX_EXPIRY_CAP_SECONDS = 365 * DAY_SECONDS;

/** Mirrors the document-service validation rules; returns one message per violated rule. */
export function validateSharePolicy(p: SharePolicyUpdate): string[] {
  const errors: string[] = [];
  const values = [p.defaultExpirySeconds, p.minExpirySeconds, p.maxExpirySeconds];
  if (values.some(v => !Number.isInteger(v) || v <= 0)) {
    errors.push('All expiry values must be positive whole numbers.');
    return errors;
  }
  if (p.maxExpirySeconds > MAX_EXPIRY_CAP_SECONDS) {
    errors.push('Maximum expiry cannot be more than 365 days.');
  }
  if (p.minExpirySeconds > p.maxExpirySeconds) {
    errors.push('Minimum expiry cannot be greater than maximum expiry.');
  }
  if (p.defaultExpirySeconds < p.minExpirySeconds || p.defaultExpirySeconds > p.maxExpirySeconds) {
    errors.push('Default expiry must be between the minimum and maximum expiry.');
  }
  return errors;
}
