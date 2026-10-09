"use client";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { Loading } from "@/components/ui";
import { api } from "@/lib/api";

export default function AppIndex() {
  const router = useRouter();
  useEffect(() => {
    api<any>("/auth/me")
      .then((r) => router.replace(r.user.organizations.length ? `/app/${r.user.organizations[0].id}` : "/signup"))
      .catch(() => router.replace("/login"));
  }, [router]);
  return <Loading />;
}
