import { AuthForm } from "@/components/AuthForm";
import { PublicNav } from "@/components/PublicNav";

export default function Signup() {
  return (<><PublicNav /><AuthForm mode="signup" /></>);
}
