import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { Notification } from "@/types";
import { NotificationRow } from "./notifications";

function makeNotification(overrides: Partial<Notification> = {}): Notification {
  return {
    id: "n1",
    type: "comment",
    title: "New comment",
    message: "Alice commented on your document",
    read: false,
    createdAt: new Date().toISOString(),
    ...overrides,
  };
}

function renderRow(notification: Notification, onMarkRead = vi.fn()) {
  const view = render(
    <MemoryRouter>
      <NotificationRow notification={notification} onMarkRead={onMarkRead} />
    </MemoryRouter>
  );
  return { ...view, onMarkRead };
}

describe("NotificationRow", () => {
  it("renders an unread row without a target as a single native button", () => {
    const { container, onMarkRead } = renderRow(makeNotification());
    const button = screen.getByRole("button", { name: /New comment/ });
    expect(button.tagName).toBe("BUTTON");
    expect(button).toHaveAttribute("type", "button");
    expect(container.querySelectorAll("[role=button], [tabindex], a, button")).toHaveLength(1);
    fireEvent.click(button);
    expect(onMarkRead).toHaveBeenCalledTimes(1);
  });

  it("renders a document row as one link that marks it read", () => {
    const { container, onMarkRead } = renderRow(
      makeNotification({ resourceId: "doc-1", resourceType: "document" })
    );
    const link = screen.getByRole("link", { name: /New comment/ });
    expect(link).toHaveAttribute("href", "/documents/doc-1");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(container.querySelectorAll("[role=button], [tabindex], a, button")).toHaveLength(1);
    fireEvent.click(link);
    expect(onMarkRead).toHaveBeenCalledTimes(1);
  });

  it("does not mark an already-read file row again", () => {
    const { onMarkRead } = renderRow(
      makeNotification({ read: true, resourceId: "file-1", resourceType: "file" })
    );
    const link = screen.getByRole("link", { name: /New comment/ });
    expect(link).toHaveAttribute("href", "/files/file-1");
    fireEvent.click(link);
    expect(onMarkRead).not.toHaveBeenCalled();
  });

  it("renders a read row without a target as non-interactive", () => {
    const { container } = renderRow(makeNotification({ read: true }));
    expect(screen.getByText("New comment")).toBeInTheDocument();
    expect(container.querySelectorAll("[role=button], [tabindex], a, button")).toHaveLength(0);
    expect(screen.queryByText("Unread")).not.toBeInTheDocument();
  });
});
