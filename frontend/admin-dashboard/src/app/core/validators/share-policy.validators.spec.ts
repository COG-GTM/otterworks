import { FormBuilder } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import {
  expiryDaysValidators, sharePolicyErrorMessage, sharePolicyOrderValidator, sharePolicyViolation,
} from './share-policy.validators';

describe('share-policy validators (OTW-81, mirrors the 422 rules)', () => {
  const policy = (defaultExpiryDays: number, minExpiryDays: number, maxExpiryDays: number) =>
    ({ defaultExpiryDays, minExpiryDays, maxExpiryDays });

  describe('sharePolicyViolation', () => {
    it('AC1/AC2: accepts default 7 within bounds 1..30', () => {
      expect(sharePolicyViolation(policy(7, 1, 30))).toBeNull();
    });

    it('accepts the edge values min = default = max and 1..365', () => {
      expect(sharePolicyViolation(policy(5, 5, 5))).toBeNull();
      expect(sharePolicyViolation(policy(1, 1, 365))).toBeNull();
    });

    it('AC3: rejects min > default', () => {
      expect(sharePolicyViolation(policy(3, 5, 30))).toContain('Minimum expiry cannot be greater than the default');
    });

    it('AC3: rejects default > max', () => {
      expect(sharePolicyViolation(policy(45, 1, 30))).toContain('Default expiry cannot be greater than the maximum');
    });

    it('AC3: rejects min < 1', () => {
      expect(sharePolicyViolation(policy(7, 0, 30))).toContain('at least 1 day');
    });

    it('AC3: rejects max > 365', () => {
      expect(sharePolicyViolation(policy(7, 1, 366))).toContain('cannot exceed 365 days');
    });

    it('rejects fractional days', () => {
      expect(sharePolicyViolation(policy(7.5, 1, 30))).toContain('whole numbers');
    });
  });

  describe('form validators', () => {
    const build = (def: unknown, min: unknown, max: unknown) => new FormBuilder().group({
      defaultExpiryDays: [def, expiryDaysValidators],
      minExpiryDays: [min, expiryDaysValidators],
      maxExpiryDays: [max, expiryDaysValidators],
    }, { validators: sharePolicyOrderValidator });

    it('valid policy produces no errors', () => {
      expect(build(7, 1, 30).valid).toBeTrue();
    });

    it('flags minAboveDefault and defaultAboveMax at group level', () => {
      expect(build(3, 5, 30).errors).toEqual({ minAboveDefault: true });
      expect(build(45, 1, 30).errors).toEqual({ defaultAboveMax: true });
    });

    it('flags per-field required, min, max and pattern errors', () => {
      const form = build(null, 0, 366);
      expect(form.get('defaultExpiryDays')!.hasError('required')).toBeTrue();
      expect(form.get('minExpiryDays')!.hasError('min')).toBeTrue();
      expect(form.get('maxExpiryDays')!.hasError('max')).toBeTrue();
      expect(build(2.5, 1, 30).get('defaultExpiryDays')!.hasError('pattern')).toBeTrue();
    });
  });

  describe('sharePolicyErrorMessage', () => {
    it('AC3: shows a string detail from a 422 verbatim', () => {
      const err = new HttpErrorResponse({ status: 422, error: { detail: 'max_expiry_days must be between 1 and 365' } });
      expect(sharePolicyErrorMessage(err)).toBe('max_expiry_days must be between 1 and 365');
    });

    it('joins FastAPI validation error lists', () => {
      const err = new HttpErrorResponse({ status: 422, error: { detail: [{ msg: 'a' }, { msg: 'b' }] } });
      expect(sharePolicyErrorMessage(err)).toBe('a; b');
    });

    it('explains 403 as workspace-owner only', () => {
      expect(sharePolicyErrorMessage(new HttpErrorResponse({ status: 403 }))).toContain('workspace owner');
    });

    it('falls back to a generic message with the status', () => {
      expect(sharePolicyErrorMessage(new HttpErrorResponse({ status: 500 }))).toContain('HTTP 500');
    });
  });
});
