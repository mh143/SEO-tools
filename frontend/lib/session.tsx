"use client";
import { createContext, useContext } from "react";

export type Me = {
  id: string; email: string; name: string; is_platform_admin: boolean;
  organizations: { id: string; name: string; role: string; plan_key: string }[];
};

export const SessionContext = createContext<{ me: Me; orgId: string; role: string; refresh: () => void } | null>(null);

export function useSession() {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession outside app layout");
  return ctx;
}

const RANK: Record<string, number> = { viewer: 0, editor: 1, admin: 2, owner: 3 };
export function hasRole(role: string, min: string) {
  return (RANK[role] ?? -1) >= RANK[min];
}
