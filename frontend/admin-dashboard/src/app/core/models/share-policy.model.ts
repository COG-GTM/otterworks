export interface SharePolicy {
  workspaceId: string;
  defaultExpiryDays: number | null;
  minExpiryDays: number;
  maxExpiryDays: number | null;
  allowNoExpiry: boolean;
}
