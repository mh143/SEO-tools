"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";

export function useApi<T = any>(path: string | null, opts: { pollMs?: number; pollWhile?: (d: T) => boolean } = {}) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState<boolean>(!!path);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollRef = useRef(opts);
  pollRef.current = opts;

  const load = useCallback(async () => {
    if (!path) return;
    try {
      const d = await api<T>(path);
      setData(d);
      setError(null);
      const { pollMs, pollWhile } = pollRef.current;
      if (pollMs && (!pollWhile || pollWhile(d))) {
        timer.current = setTimeout(load, pollMs);
      }
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    setLoading(!!path);
    load();
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [load]);

  const reload = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    return load();
  }, [load]);

  return { data, error, loading, reload, setData };
}
