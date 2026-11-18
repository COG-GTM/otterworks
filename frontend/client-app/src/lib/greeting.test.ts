import { describe, it, expect } from "vitest";
import { getGreeting, getTimeOfDayGreeting } from "./greeting";

function at(hours: number, minutes = 0): Date {
  return new Date(2026, 0, 15, hours, minutes, 0, 0);
}

describe("getTimeOfDayGreeting", () => {
  it.each([
    [0, 0, "Good evening"],
    [4, 59, "Good evening"],
    [5, 0, "Good morning"],
    [11, 59, "Good morning"],
    [12, 0, "Good afternoon"],
    [17, 59, "Good afternoon"],
    [18, 0, "Good evening"],
    [23, 59, "Good evening"],
  ])("at %i:%i returns %s", (h, m, expected) => {
    expect(getTimeOfDayGreeting(at(h, m))).toBe(expected);
  });
});

describe("getGreeting", () => {
  it("appends the display name", () => {
    expect(getGreeting("Sam", at(9))).toBe("Good morning, Sam");
    expect(getGreeting("Sam", at(13))).toBe("Good afternoon, Sam");
    expect(getGreeting("Sam", at(20))).toBe("Good evening, Sam");
  });

  it.each([undefined, null, "", "   "])("omits the name when display name is %j", (name) => {
    expect(getGreeting(name, at(9))).toBe("Good morning");
  });
});
