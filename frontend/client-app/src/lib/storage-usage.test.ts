import { describe, it, expect } from "vitest";
import { getStorageUsageStatus } from "./storage-usage";

describe("getStorageUsageStatus", () => {
  it("is normal at 0% used", () => {
    expect(getStorageUsageStatus(0, 1000)).toEqual({
      percent: 0,
      displayPercent: 0,
      level: "normal",
      showWarning: false,
    });
  });

  it("is normal at 79% used", () => {
    const status = getStorageUsageStatus(79, 100);
    expect(status.level).toBe("normal");
    expect(status.showWarning).toBe(false);
    expect(status.displayPercent).toBe(79);
  });

  it("stays normal just below 80% and does not round the display up to 80", () => {
    const status = getStorageUsageStatus(799, 1000);
    expect(status.level).toBe("normal");
    expect(status.displayPercent).toBe(79);
  });

  it("warns from 80% used", () => {
    const status = getStorageUsageStatus(80, 100);
    expect(status.level).toBe("warning");
    expect(status.showWarning).toBe(true);
    expect(status.displayPercent).toBe(80);
  });

  it("is critical from 95% used", () => {
    const status = getStorageUsageStatus(95, 100);
    expect(status.level).toBe("critical");
    expect(status.showWarning).toBe(true);
    expect(status.displayPercent).toBe(95);
  });

  it("is critical at 100% used", () => {
    const status = getStorageUsageStatus(100, 100);
    expect(status.level).toBe("critical");
    expect(status.percent).toBe(100);
    expect(status.displayPercent).toBe(100);
  });

  it("clamps usage above the quota to 100%", () => {
    const status = getStorageUsageStatus(150, 100);
    expect(status.percent).toBe(100);
    expect(status.level).toBe("critical");
  });

  it("treats a total of 0 as 0% used without warning", () => {
    expect(getStorageUsageStatus(0, 0)).toEqual({
      percent: 0,
      displayPercent: 0,
      level: "normal",
      showWarning: false,
    });
    expect(getStorageUsageStatus(500, 0).level).toBe("normal");
  });
});
