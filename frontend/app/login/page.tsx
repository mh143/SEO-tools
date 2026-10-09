import { AuthForm } from "@/components/AuthForm";
import { PublicNav } from "@/components/PublicNav";

export default function Login() {
  return (<><PublicNav /><AuthForm mode="login" /></>);
}
