import { AbstractControl, ValidationErrors, ValidatorFn, Validators } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { SHARE_POLICY_LIMITS, SharePolicyUpdate } from '../models/share-policy.model';

/** Per-field rules: a whole number of days within the service's hard limits. */
export const expiryDaysValidators: ValidatorFn[] = [
  Validators.required,
  Validators.pattern(/^\d+$/),
  Validators.min(SHARE_POLICY_LIMITS.floorDays),
  Validators.max(SHARE_POLICY_LIMITS.ceilingDays),
];

/**
 * Mirrors the document-service 422 rules for PUT /documents/share-policy:
 * min >= 1, max <= 365, min <= default <= max.
 * Returns a human-readable message, or null when the policy is valid.
 */
export function sharePolicyViolation(policy: SharePolicyUpdate): string | null {
  const { defaultExpiryDays: def, minExpiryDays: min, maxExpiryDays: max } = policy;
  const { floorDays, ceilingDays } = SHARE_POLICY_LIMITS;
  if ([def, min, max].some(v => !Number.isInteger(v))) {
    return 'Expiry values must be whole numbers of days.';
  }
  if (min < floorDays) return `Minimum expiry must be at least ${floorDays} day.`;
  if (max > ceilingDays) return `Maximum expiry cannot exceed ${ceilingDays} days.`;
  if (min > def) return 'Minimum expiry cannot be greater than the default expiry.';
  if (def > max) return 'Default expiry cannot be greater than the maximum expiry.';
  return null;
}

/** Form-group validator for the cross-field ordering min <= default <= max. */
export const sharePolicyOrderValidator: ValidatorFn = (group: AbstractControl): ValidationErrors | null => {
  const def = Number(group.get('defaultExpiryDays')?.value);
  const min = Number(group.get('minExpiryDays')?.value);
  const max = Number(group.get('maxExpiryDays')?.value);
  if ([def, min, max].some(v => !Number.isFinite(v))) return null;
  const errors: ValidationErrors = {};
  if (min > def) errors['minAboveDefault'] = true;
  if (def > max) errors['defaultAboveMax'] = true;
  return Object.keys(errors).length ? errors : null;
};

/** Extracts a displayable message from a document-service error response. */
export function sharePolicyErrorMessage(err: unknown): string {
  if (err instanceof HttpErrorResponse) {
    const detail = err.error?.detail;
    if (typeof detail === 'string' && detail.trim()) return detail;
    if (Array.isArray(detail) && detail.length) {
      return detail.map((d: { msg?: string }) => d?.msg ?? String(d)).join('; ');
    }
    if (err.status === 403) return 'Only a workspace owner can change the share-link expiry policy.';
    if (err.status === 0) return 'Could not reach the document service. Please try again.';
    return `The document service returned an error (HTTP ${err.status}). Please try again.`;
  }
  return 'Something went wrong. Please try again.';
}
