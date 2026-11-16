import { getPasswordStrength, type PasswordStrengthLevel } from "@/lib/password-strength";
import { cn } from "@/lib/utils";

const FILLED_SEGMENTS: Record<PasswordStrengthLevel, number> = {
  weak: 1,
  fair: 2,
  strong: 3,
};

const LEVEL_STYLES: Record<PasswordStrengthLevel, { bar: string; text: string }> = {
  weak: { bar: "bg-red-500", text: "text-red-600" },
  fair: { bar: "bg-amber-500", text: "text-amber-600" },
  strong: { bar: "bg-green-500", text: "text-green-600" },
};

export function PasswordStrengthMeter({ password }: { password: string }) {
  const strength = getPasswordStrength(password);
  if (!strength) return null;

  const filled = FILLED_SEGMENTS[strength.level];
  const styles = LEVEL_STYLES[strength.level];

  return (
    <div className="mt-2" data-testid="password-strength">
      <div
        className="flex gap-1"
        role="meter"
        aria-label="Password strength"
        aria-valuemin={1}
        aria-valuemax={3}
        aria-valuenow={filled}
        aria-valuetext={strength.label}
      >
        {[1, 2, 3].map((segment) => (
          <div
            key={segment}
            className={cn(
              "h-1.5 flex-1 rounded-full transition-colors",
              segment <= filled ? styles.bar : "bg-gray-200"
            )}
          />
        ))}
      </div>
      <p className={cn("text-xs mt-1 font-medium", styles.text)}>
        Password strength: {strength.label}
      </p>
    </div>
  );
}
