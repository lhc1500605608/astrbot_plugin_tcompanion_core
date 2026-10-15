import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  Outlet,
  Link,
  createRootRouteWithContext,
  type ErrorComponentProps,
} from "@tanstack/react-router";
import { HearthlightProvider } from "@/lib/hearthlight/context";
import { AppShell } from "@/components/hl/AppShell";
import { Toaster } from "@/components/ui/sonner";
function ErrorView({ reset }: ErrorComponentProps) {
  return (
    <div role="alert" className="p-10 text-center">
      <h1 className="text-xl">页面加载失败</h1>
      <p className="my-4">请重试，或返回总览。</p>
      <button className="mr-4 underline" onClick={reset}>
        重试
      </button>
      <Link to="/">回到总览</Link>
    </div>
  );
}
export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  component: Root,
  errorComponent: ErrorView,
  notFoundComponent: () => (
    <div className="p-10">
      没有找到此页面。<Link to="/">回到总览</Link>
    </div>
  ),
});
function Root() {
  const { queryClient } = Route.useRouteContext();
  return (
    <QueryClientProvider client={queryClient}>
      <HearthlightProvider>
        <AppShell>
          <Outlet />
        </AppShell>
        <Toaster position="bottom-right" />
      </HearthlightProvider>
    </QueryClientProvider>
  );
}
