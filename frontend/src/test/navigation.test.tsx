import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { TraceDrawer } from "../components/TraceDrawer";
import { Tabs } from "../components/widgets";
import { mockFetch, renderWithProviders } from "./render";

type Tab = "overview" | "criteria" | "sources";

function TabExample() {
  const [tab, setTab] = useState<Tab>("overview");
  return (
    <>
      <Tabs<Tab> tabs={[{ id: "overview", label: "Overview" }, { id: "criteria", label: "Criteria" }, { id: "sources", label: "Sources" }]} value={tab} onChange={setTab} />
      <div id={`panel-${tab}`} role="tabpanel" aria-labelledby={`tab-${tab}`}>{tab} content</div>
      <button type="button">After tabs</button>
    </>
  );
}

function DrawerExample() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>Open criterion trace</button>
      <button type="button">Outside drawer</button>
      <TraceDrawer assessmentId="assessment-1" criterionCode={open ? "SAF-01" : null} onClose={() => setOpen(false)} />
    </>
  );
}

describe("Tab keyboard navigation", () => {
  it("moves focus and selection with arrow keys, wrapping at either end", async () => {
    const user = userEvent.setup();
    renderWithProviders(<TabExample />);
    const overview = screen.getByRole("tab", { name: "Overview" });
    const criteria = screen.getByRole("tab", { name: "Criteria" });
    const sources = screen.getByRole("tab", { name: "Sources" });

    await user.tab();
    expect(overview).toHaveFocus();
    await user.keyboard("{ArrowRight}");
    expect(criteria).toHaveFocus();
    expect(criteria).toHaveAttribute("aria-selected", "true");
    expect(criteria).toHaveAttribute("tabindex", "0");
    expect(overview).toHaveAttribute("aria-selected", "false");
    expect(overview).toHaveAttribute("tabindex", "-1");
    expect(screen.getByRole("tabpanel", { name: "Criteria" })).toHaveTextContent("criteria content");

    await user.keyboard("{ArrowRight}{ArrowRight}");
    expect(overview).toHaveFocus();
    expect(overview).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{ArrowLeft}");
    expect(sources).toHaveFocus();
    expect(sources).toHaveAttribute("aria-selected", "true");
  });

  it("supports Home and End while keeping only the active tab in the Tab order", async () => {
    const user = userEvent.setup();
    renderWithProviders(<TabExample />);
    await user.tab();
    await user.keyboard("{End}");
    const sources = screen.getByRole("tab", { name: "Sources" });
    expect(sources).toHaveFocus();
    expect(sources).toHaveAttribute("aria-selected", "true");
    await user.tab();
    expect(screen.getByRole("button", { name: "After tabs" })).toHaveFocus();
    await user.tab({ shift: true });
    expect(sources).toHaveFocus();
    await user.keyboard("{Home}");
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveFocus();
    expect(screen.getAllByRole("tab").filter((tab) => tab.tabIndex === 0)).toHaveLength(1);
  });
});

describe("Trace drawer keyboard navigation", () => {
  it("traps focus, closes with Escape, and restores the trigger and previous scroll setting", async () => {
    mockFetch((url) => url.endsWith("/trace/SAF-01") ? {
      body: {
        assessment_id: "assessment-1",
        criteria: [{
          criterion_code: "SAF-01", criterion_name: "Risk Mitigation", level: 3, coverage_state: "observed", confidence: 70,
          rules: [], finding: null,
          evidence: [{ link_id: "evidence-1", quote: "Risk is reviewed regularly.", polarity: "supports", admissibility: "admissible", maturity_rung: "documented", independence: "self", publisher_name: "Acme", published_at: null, canonical_url: "https://acme.example/governance", char_start: 0, char_end: 32 }],
        }],
      },
    } : undefined);
    const user = userEvent.setup();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "auto";
    const { unmount } = renderWithProviders(<DrawerExample />);
    try {
      const trigger = screen.getByRole("button", { name: "Open criterion trace" });
      await user.click(trigger);
      const dialog = await screen.findByRole("dialog");
      const close = within(dialog).getByRole("button", { name: "Close trace" });
      const source = await within(dialog).findByRole("link", { name: "source" });
      expect(close).toHaveFocus();
      expect(document.body.style.overflow).toBe("hidden");

      await user.tab({ shift: true });
      expect(source).toHaveFocus();
      await user.tab();
      expect(close).toHaveFocus();
      await user.tab();
      expect(source).toHaveFocus();
      await user.tab();
      expect(close).toHaveFocus();

      await user.keyboard("{Escape}");
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(trigger).toHaveFocus();
      expect(document.body.style.overflow).toBe("auto");
    } finally {
      unmount();
      document.body.style.overflow = previousOverflow;
    }
  });
});
