import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, it, expect } from "vitest";
import { HearthlightProvider, useHL } from "./context";
function Probe() {
  const c = useHL();
  return (
    <>
      <p>{c.connection.status}</p>
      <p>{c.adapter?.mode ?? "none"}</p>
      <button onClick={c.enterDemo}>演示</button>
    </>
  );
}
afterEach(() => {
  cleanup();
  delete window.AstrBotPluginPage;
});
describe("host failure boundary", () => {
  it("does not replace failed host with demo until explicitly requested", async () => {
    window.AstrBotPluginPage = {
      ready: async () => {
        throw new Error("unavailable");
      },
      apiGet: async () => ({}),
      apiPost: async () => ({}),
    };
    render(
      <QueryClientProvider client={new QueryClient()}>
        <HearthlightProvider>
          <Probe />
        </HearthlightProvider>
      </QueryClientProvider>,
    );
    await screen.findByText("error");
    expect(screen.getByText("none")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "演示" }));
    await screen.findAllByText("demo");
  });
});
