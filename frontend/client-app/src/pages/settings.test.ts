import { describe, it, expect } from "vitest";
import { profileSchema } from "./settings";

// auth-service UpdateProfileRequest caps displayName at 100 characters.
describe("profileSchema", () => {
  const email = "ada@example.com";

  it("accepts a 100-character name", () => {
    expect(profileSchema.safeParse({ displayName: "a".repeat(100), email }).success).toBe(true);
  });

  it("rejects a name longer than 100 characters", () => {
    expect(profileSchema.safeParse({ displayName: "a".repeat(101), email }).success).toBe(false);
  });
});
