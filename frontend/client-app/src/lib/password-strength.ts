export type PasswordStrengthLevel = "weak" | "fair" | "strong";

export interface PasswordStrength {
  level: PasswordStrengthLevel;
  label: "Weak" | "Fair" | "Strong";
  score: number;
}

export const MIN_PASSWORD_LENGTH = 8;

const CHARACTER_CLASSES = [/[a-z]/, /[A-Z]/, /[0-9]/, /[^A-Za-z0-9]/];
const LENGTH_THRESHOLDS = [MIN_PASSWORD_LENGTH, 12, 16];

const LABELS: Record<PasswordStrengthLevel, PasswordStrength["label"]> = {
  weak: "Weak",
  fair: "Fair",
  strong: "Strong",
};

/**
 * Scores a password from its length and its mix of lowercase, uppercase,
 * digits and symbols. Returns null for an empty password. Passwords shorter
 * than the minimum length are always "weak".
 */
export function getPasswordStrength(password: string): PasswordStrength | null {
  if (!password) return null;

  const lengthPoints = LENGTH_THRESHOLDS.filter((n) => password.length >= n).length;
  const classCount = CHARACTER_CLASSES.filter((re) => re.test(password)).length;
  const score = lengthPoints + Math.max(0, classCount - 1);

  let level: PasswordStrengthLevel;
  if (password.length < MIN_PASSWORD_LENGTH || score <= 2) level = "weak";
  else if (score === 3) level = "fair";
  else level = "strong";

  return { level, label: LABELS[level], score };
}
