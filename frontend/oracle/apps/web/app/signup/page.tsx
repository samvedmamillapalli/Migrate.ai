import { redirect } from "next/navigation"

/** Signup is handled on /login (register mode) when AUTH_ENABLED. */
export default function SignupPage() {
  redirect("/login")
}
