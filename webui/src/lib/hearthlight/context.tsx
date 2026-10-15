import { useQuery, useQueryClient, useIsFetching } from "@tanstack/react-query";
import {
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createDemoAdapter, type DemoScenario } from "./demo";
import { detectHost } from "./host";
import type { HearthlightAdapter } from "./types";

import { HLContext, type Connection, type Theme, type Ctx } from "./state";

const THEME_KEY = "hearthlight-theme";

export function HearthlightProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [adapter, setAdapter] = useState<HearthlightAdapter | null>(null);
  const [connection, setConnection] = useState<Connection>({ status: "detecting" });
  const [scenario, setScenarioState] = useState<DemoScenario>("normal");
  const scenarioRef = useRef<DemoScenario>("normal");
  const [theme, setTheme] = useState<Theme>("light");
  const [persona, setPersona] = useState("all");
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);

  useEffect(() => {
    setTheme(document.documentElement.classList.contains("dark") ? "dark" : "light");
    let alive = true;
    detectHost().then((r) => {
      if (!alive) return;
      if (r.status === "host") {
        setAdapter(r.adapter);
        setConnection({ status: "host" });
      } else if (r.status === "ready-failed") {
        setConnection({ status: "error", message: r.message });
      } else {
        setAdapter(createDemoAdapter(() => scenarioRef.current));
        setConnection({ status: "demo", reason: "no-sdk" });
      }
    });
    return () => {
      alive = false;
    };
  }, []);

  const enterDemo = useCallback(() => {
    setAdapter(createDemoAdapter(() => scenarioRef.current));
    setConnection({ status: "demo", reason: "no-sdk" });
    qc.removeQueries({ queryKey: ["hl"] });
  }, [qc]);

  const toggleTheme = useCallback(() => {
    setTheme((t) => {
      const n = t === "dark" ? "light" : "dark";
      document.documentElement.classList.toggle("dark", n === "dark");
      try {
        localStorage.setItem(THEME_KEY, n);
      } catch {
        /* ignore */
      }
      return n;
    });
  }, []);

  const setScenario = useCallback(
    (s: DemoScenario) => {
      scenarioRef.current = s;
      setScenarioState(s);
      qc.resetQueries({ queryKey: ["hl"] });
    },
    [qc],
  );

  const refresh = useCallback(() => {
    qc.invalidateQueries({ queryKey: ["hl"] });
  }, [qc]);

  const markUpdated = useCallback((t: number) => setLastUpdated((p) => (p && p > t ? p : t)), []);

  const value = useMemo<Ctx>(
    () => ({
      adapter,
      connection,
      scenario,
      setScenario,
      theme,
      toggleTheme,
      persona,
      setPersona,
      autoRefresh,
      setAutoRefresh,
      refresh,
      lastUpdated,
      markUpdated,
      enterDemo,
    }),
    [
      adapter,
      connection,
      scenario,
      setScenario,
      theme,
      toggleTheme,
      persona,
      autoRefresh,
      refresh,
      lastUpdated,
      markUpdated,
      enterDemo,
    ],
  );

  return <HLContext.Provider value={value}>{children}</HLContext.Provider>;
}

export function useHL() {
  const c = useContext(HLContext);
  if (!c) throw new Error("useHL outside provider");
  return c;
}

export const useHLFetching = () => useIsFetching({ queryKey: ["hl"] });

type Fetcher<T> = (a: HearthlightAdapter) => Promise<T>;
function useHLQuery<T>(ep: string, fn: Fetcher<T>) {
  const { adapter, scenario, autoRefresh, markUpdated } = useHL();
  const q = useQuery({
    queryKey: ["hl", adapter?.mode ?? "none", scenario, ep],
    queryFn: () => fn(adapter as HearthlightAdapter),
    enabled: !!adapter,
    retry: false,
    refetchOnWindowFocus: false,
    refetchInterval: autoRefresh ? 60_000 : false,
  });
  useEffect(() => {
    if (q.dataUpdatedAt) markUpdated(q.dataUpdatedAt);
  }, [q.dataUpdatedAt, markUpdated]);
  return q;
}

export const useLife = () => useHLQuery("life-state", (a) => a.getLifeState());
export const useRelationships = () => useHLQuery("relationships", (a) => a.getRelationships());
export const useEmotions = () => useHLQuery("emotion-state", (a) => a.getEmotionState());
export const useGroups = () => useHLQuery("group-state", (a) => a.getGroupState());
export const useGrowth = () => useHLQuery("growth-state", (a) => a.getGrowthState());
export const useMotivation = () => useHLQuery("motivation-log", (a) => a.getMotivationLog());
export const usePersonKeys = () => useHLQuery("person/keys", (a) => a.getPersonKeys());

/** Persona display names come from life-state when available, else the raw id. */
export function usePersonaName() {
  const life = useLife();
  return useCallback(
    (id: string) => life.data?.items.find((i) => i.persona_id === id)?.persona_name ?? id,
    [life.data],
  );
}
