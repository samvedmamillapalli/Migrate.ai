import { LoginForm } from "@/components/login-form"
import { AuthShell } from "@/components/auth-shell"

export default function LoginPage() {
  return (
    <AuthShell>
      <LoginForm />
    </AuthShell>
  )
}
