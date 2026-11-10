export const SHARING_POLICY_LIMITS = { min: 1, max: 90 } as const;

export const DEFAULT_SHARING_POLICY: SharingPolicy = {
  defaultExpiryDays: 30,
  minExpiryDays: 1,
  maxExpiryDays: 90,
};

export interface SharingPolicy {
  defaultExpiryDays: number;
  minExpiryDays: number;
  maxExpiryDays: number;
}
