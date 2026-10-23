import { AxiosError, type AxiosResponse } from "axios";
import { describe, expect, it } from "vitest";
import { getApiErrorMessage } from "./utils";

describe("getApiErrorMessage", () => {
  it("returns the API message from an Axios error", () => {
    const error = new AxiosError("Request failed");
    error.response = {
      data: { message: "name cannot be empty" },
    } as AxiosResponse;

    expect(getApiErrorMessage(error, "Something went wrong")).toBe("name cannot be empty");
  });

  it("returns the fallback when an Axios error has no response data", () => {
    const error = new AxiosError("Request failed");
    error.response = { data: {} } as AxiosResponse;

    expect(getApiErrorMessage(error, "Something went wrong")).toBe("Something went wrong");
  });

  it("returns the fallback for a plain Error", () => {
    expect(getApiErrorMessage(new Error("Unexpected failure"), "Something went wrong")).toBe(
      "Something went wrong",
    );
  });
});
