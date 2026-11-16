import { describe, it, expect } from "vitest";
import { getPasswordStrength } from "./password-strength";

describe("getPasswordStrength", () => {
  it("returns null for an empty password", () => {
    expect(getPasswordStrength("")).toBeNull();
  });

  it("rates passwords shorter than 8 characters as weak, whatever their mix", () => {
    expect(getPasswordStrength("a")?.level).toBe("weak");
    expect(getPasswordStrength("Ab1!xyz")?.level).toBe("weak");
  });

  it("rates a long password with a single character class as weak", () => {
    expect(getPasswordStrength("password")?.level).toBe("weak");
    expect(getPasswordStrength("abcdefghijkl")?.level).toBe("weak");
  });

  it("rates a password with a moderate mix as fair", () => {
    expect(getPasswordStrength("Password1")?.level).toBe("fair");
    expect(getPasswordStrength("abcdefgh1234")?.level).toBe("fair");
    expect(getPasswordStrength("correcthorsebattery")?.level).toBe("fair");
  });

  it("rates a password with a rich mix or more length as strong", () => {
    expect(getPasswordStrength("Password1!")?.level).toBe("strong");
    expect(getPasswordStrength("Abcdefghijkl1")?.level).toBe("strong");
    expect(getPasswordStrength("correct horse battery staple")?.level).toBe("strong");
  });

  it("counts lowercase, uppercase, numbers and symbols as separate classes", () => {
    const base = getPasswordStrength("abcdefgh")!.score;
    expect(getPasswordStrength("abcdefgH")!.score).toBe(base + 1);
    expect(getPasswordStrength("abcdefH1")!.score).toBe(base + 2);
    expect(getPasswordStrength("abcdeH1!")!.score).toBe(base + 3);
  });

  it("gives extra points for length", () => {
    expect(getPasswordStrength("aaaaaaaa")!.score).toBe(1);
    expect(getPasswordStrength("a".repeat(12))!.score).toBe(2);
    expect(getPasswordStrength("a".repeat(16))!.score).toBe(3);
  });

  it("exposes a display label matching the level", () => {
    expect(getPasswordStrength("password")?.label).toBe("Weak");
    expect(getPasswordStrength("Password1")?.label).toBe("Fair");
    expect(getPasswordStrength("Password1!")?.label).toBe("Strong");
  });
});
