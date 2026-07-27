import { SignupForm } from "@/components/signup-form"
import { AuthShell } from "@/components/auth-shell"

export default function GetStartedPage() {
  return (
    <AuthShell>
      <SignupForm />
    </AuthShell>
  )
}
