import { createContext } from "react";
import type { DemoScenario } from "./demo";
import type { HearthlightAdapter } from "./types";

export type Connection =
  | { status: "detecting" }
  | { status: "host" }
  | { status: "error"; message: string }
  | { status: "demo"; reason: "no-sdk" | "ready-failed"; message?: string };

export type Theme = "light" | "dark";

export interface Ctx {
  adapter: HearthlightAdapter | null;
  connection: Connection;
  scenario: DemoScenario;
  setScenario: (s: DemoScenario) => void;
  theme: Theme;
  toggleTheme: () => void;
  persona: string;
  setPersona: (p: string) => void;
  autoRefresh: boolean;
  setAutoRefresh: (v: boolean) => void;
  refresh: () => void;
  lastUpdated: number | null;
  markUpdated: (t: number) => void;
  enterDemo: () => void;
}

export const HLContext = createContext<Ctx | null>(null);
