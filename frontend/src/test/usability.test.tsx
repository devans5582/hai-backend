import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { Settings } from "../pages/Settings";
import { Verify } from "../pages/Verify";
import { mockFetch, renderWithProviders } from "./render";

describe("Certificate verification usability", () => {
  it("explains empty or incomplete numbers without sending a request", async () => {
    const user = userEvent.setup();
    const { calls } = mockFetch(() => undefined);
    renderWithProviders(<Verify />, { route: "/verify", path: "/verify" });

    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a complete certificate number.");
    const input = screen.getByLabelText("Certificate number");
    expect(input).toHaveAttribute("aria-invalid", "true");

    await user.type(input, "HAI");
    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a complete certificate number.");
    expect(calls).toHaveLength(0);
  });

  it("checks again when the same certificate number is submitted", async () => {
    const user = userEvent.setup();
    let attempts = 0;
    const { calls } = mockFetch((url) => {
      if (!url.endsWith("/v1/certifications/HAI-RETRY/verify")) return undefined;
      attempts += 1;
      return { body: {
        valid: attempts > 1,
        status: attempts > 1 ? "valid" : "expired",
        certificate_number: "HAI-RETRY",
        organization: "Example Organization",
        hai_score: 81.5,
        signed_at: "2026-10-24T12:00:00Z",
        expires_at: "2027-10-24T12:00:00Z",
        reviewer: "reviewer-1",
        methodology_version: "1.0.0",
      } };
    });
    renderWithProviders(<Verify />, { route: "/verify?number=HAI-RETRY", path: "/verify" });

    expect(await screen.findByText("expired")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByText("Valid")).toBeInTheDocument();
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(screen.getByLabelText("Certificate number")).toHaveValue("HAI-RETRY");
  });
});

describe("Credential settings usability", () => {
  it("masks saved secrets and lets the user reveal and hide each one", async () => {
    const user = userEvent.setup();
    localStorage.setItem("hai.apiKey", "hai_example.fake-secret");
    localStorage.setItem("hai.reviewerToken", "example.fake-token.value");
    renderWithProviders(<Settings />, { route: "/settings", path: "/settings" });

    const key = screen.getByLabelText("API key");
    const token = screen.getByLabelText("Reviewer token (JWT)");
    expect(key).toHaveAttribute("type", "password");
    expect(token).toHaveAttribute("type", "password");
    await user.click(screen.getByRole("button", { name: "Show API key" }));
    expect(key).toHaveAttribute("type", "text");
    expect(token).toHaveAttribute("type", "password");
    await user.click(screen.getByRole("button", { name: "Hide API key" }));
    expect(key).toHaveAttribute("type", "password");
    await user.click(screen.getByRole("button", { name: "Show reviewer token" }));
    expect(token).toHaveAttribute("type", "text");
    await user.click(screen.getByRole("button", { name: "Hide reviewer token" }));
    expect(token).toHaveAttribute("type", "password");
  });

  it("clears the saved confirmation when credentials have unsaved edits", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Settings />, { route: "/settings", path: "/settings" });

    const key = screen.getByLabelText("API key");
    await user.type(key, "hai_example.fake-secret");
    await user.click(screen.getByRole("button", { name: "Save credentials" }));
    expect(screen.getByRole("status")).toHaveTextContent("Credentials saved.");
    expect(localStorage.getItem("hai.apiKey")).toBe("hai_example.fake-secret");

    await user.type(key, "-edited");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByText("You have unsaved changes.")).toBeInTheDocument();
    expect(localStorage.getItem("hai.apiKey")).toBe("hai_example.fake-secret");
  });
});
