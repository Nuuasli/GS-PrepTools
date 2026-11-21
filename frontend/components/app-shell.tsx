"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Film, ImageDown, Layers3, Menu, X } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";

const navigation = [
  { href: "/", label: "Video Processing", icon: Film },
  { href: "/image-downscale", label: "Image Downscale", icon: ImageDown },
];

const routeContext: Record<string, { title: string; context: string }> = {
  "/": {
    title: "Video Processing",
    context: "Prepare curated image datasets from source video",
  },
  "/image-downscale": {
    title: "Image Downscale",
    context: "Resize extracted images without altering source files",
  },
  "/processing": {
    title: "Processing",
    context: "Monitor the active preparation pipeline",
  },
  "/result": {
    title: "Dataset Result",
    context: "Review and export the completed dataset",
  },
};

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);
  const current = routeContext[pathname] ?? {
    title: "Workspace",
    context: "GS-PrepTools research workspace",
  };

  return (
    <div className="min-h-screen bg-background lg:grid lg:grid-cols-[248px_minmax(0,1fr)]">
      {mobileOpen && (
        <button
          type="button"
          aria-label="Close navigation"
          className="fixed inset-0 z-40 bg-black/35 lg:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-50 flex w-[248px] flex-col border-r border-white/8 bg-[#151515] text-white transition-transform duration-200 lg:sticky lg:top-0 lg:h-screen lg:translate-x-0",
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        )}
      >
        <div className="flex h-[76px] items-center justify-between border-b border-white/8 px-6">
          <Link
            href="/"
            className="flex items-center gap-3 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70"
            onClick={() => setMobileOpen(false)}
          >
            <span className="grid h-9 w-9 place-items-center rounded-lg border border-white/15 bg-white/5">
              <Layers3 className="h-5 w-5 text-[#d66a52]" />
            </span>
            <span>
              <span className="block text-[15px] font-semibold tracking-tight">
                GS-PrepTools
              </span>
              <span className="block text-[10px] text-white/48">
                Research workspace
              </span>
            </span>
          </Link>
          <button
            type="button"
            aria-label="Close navigation"
            className="rounded-md p-2 text-white/60 hover:bg-white/8 hover:text-white lg:hidden"
            onClick={() => setMobileOpen(false)}
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <nav aria-label="Primary navigation" className="flex-1 px-4 py-7">
          <p className="mb-3 px-3 text-[11px] font-medium text-white/38">
            Workspace
          </p>
          <div className="space-y-1.5">
            {navigation.map((item) => {
              const Icon = item.icon;
              const active =
                item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  onClick={() => setMobileOpen(false)}
                  className={cn(
                    "relative flex h-11 items-center gap-3 rounded-lg px-3 text-sm font-medium text-white/62 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/70",
                    active
                      ? "bg-[#262626] text-white"
                      : "hover:bg-white/6 hover:text-white"
                  )}
                >
                  {active && (
                    <span className="absolute -left-4 h-6 w-[3px] rounded-r-full bg-[#c64a31]" />
                  )}
                  <Icon className="h-[18px] w-[18px]" />
                  {item.label}
                </Link>
              );
            })}
          </div>
        </nav>

        <div className="border-t border-white/8 px-6 py-5">
          <div className="flex items-start gap-3 text-xs text-white/45">
            <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-[#c64a31]" />
            <p className="leading-5">
              Standalone preprocessing for research image datasets.
            </p>
          </div>
        </div>
      </aside>

      <div className="min-w-0">
        <header className="sticky top-0 z-30 flex h-[76px] items-center border-b border-border bg-[color:var(--header)]/95 px-4 backdrop-blur-sm sm:px-7 lg:px-9">
          <button
            type="button"
            aria-label="Open navigation"
            aria-expanded={mobileOpen}
            className="mr-3 rounded-lg border border-border bg-card p-2 text-foreground hover:bg-muted lg:hidden"
            onClick={() => setMobileOpen(true)}
          >
            <Menu className="h-5 w-5" />
          </button>
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <span>GS-PrepTools</span>
              <span aria-hidden="true">/</span>
              <span className="font-medium text-foreground">{current.title}</span>
            </div>
            <p className="mt-1 truncate text-sm text-muted-foreground">
              {current.context}
            </p>
          </div>
          <div className="ml-auto hidden items-center gap-2 rounded-full border border-border bg-card px-3 py-1.5 text-xs text-muted-foreground sm:flex">
            <span className="h-1.5 w-1.5 rounded-full bg-success" />
            Local workspace
          </div>
        </header>
        <div className="min-h-[calc(100vh-76px)]">{children}</div>
      </div>
    </div>
  );
}
