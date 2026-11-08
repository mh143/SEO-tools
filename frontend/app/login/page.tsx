import { Suspense } from "react";
import { AuthForm, AuthShell } from "@/components/AuthForm";

export const metadata = { title: "Log in" };

export default function Login() {
  return <AuthShell><Suspense><AuthForm mode="login" /></Suspense></AuthShell>;
}
