import { afterEach, describe, expect, it, vi } from "vitest";
import { filesApi } from "./api";
import type { FileItem, PaginatedResponse } from "@/types";

function page(ids: string[], hasMore: boolean, pageNo: number): PaginatedResponse<FileItem> {
  return {
    data: ids.map((id) => ({ id, name: id, ownerId: "u" }) as FileItem),
    total: 0,
    page: pageNo,
    pageSize: ids.length,
    hasMore,
  };
}

describe("filesApi.getAllShared", () => {
  afterEach(() => vi.restoreAllMocks());

  it("follows hasMore until every page of shared files is loaded", async () => {
    const spy = vi
      .spyOn(filesApi, "getShared")
      .mockResolvedValueOnce(page(["a", "b"], true, 1))
      .mockResolvedValueOnce(page(["c"], false, 2));

    const files = await filesApi.getAllShared(2);

    expect(files.map((f) => f.id)).toEqual(["a", "b", "c"]);
    expect(spy).toHaveBeenNthCalledWith(1, 1, 2);
    expect(spy).toHaveBeenNthCalledWith(2, 2, 2);
  });

  it("stops at maxPages", async () => {
    const spy = vi.spyOn(filesApi, "getShared").mockResolvedValue(page(["x"], true, 1));

    await filesApi.getAllShared(1, 3);

    expect(spy).toHaveBeenCalledTimes(3);
  });
});
