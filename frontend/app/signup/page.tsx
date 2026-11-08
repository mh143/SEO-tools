import { Suspense } from "react";
import { AuthForm, AuthShell } from "@/components/AuthForm";

export const metadata = { title: "Create account" };

export default function Signup() {
  return <AuthShell><Suspense><AuthForm mode="signup" /></Suspense></AuthShell>;
}
