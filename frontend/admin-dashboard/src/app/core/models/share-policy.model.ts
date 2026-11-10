export const SHARE_POLICY_MIN_DAYS = 1;
export const SHARE_POLICY_MAX_DAYS = 90;
export const SHARE_POLICY_DEFAULT_DAYS = 30;

export interface WorkspaceSharePolicy {
  workspaceId: string;
  defaultDays: number;
  maxDays: number;
  updatedAt: string | null;
  updatedBy: string | null;
}

export interface WorkspaceSharePolicyUpdate {
  defaultDays: number;
  maxDays: number;
}
