import type { Appearance } from "@clerk/types"

/**
 * Clerk auth widgets styled for the Dream light theme
 * (warm parchment + terracotta). Explicit colors — Tailwind
 * classes do not apply inside Clerk's shadow DOM/iframe styles.
 */
export const clerkAppearance: Appearance = {
  variables: {
    colorBackground: "oklch(0.985 0.005 85)",
    colorText: "oklch(0.245 0.008 40)",
    colorTextSecondary: "oklch(0.55 0.012 50)",
    colorInputBackground: "oklch(0.968 0.008 85)",
    colorInputText: "oklch(0.245 0.008 40)",
    colorPrimary: "oklch(0.4 0.135 25.8)",
    colorPrimaryForeground: "oklch(0.985 0.006 85)",
    colorNeutral: "oklch(0.55 0.012 50)",
    colorDanger: "oklch(0.577 0.245 27.325)",
    colorSuccess: "oklch(0.55 0.12 155)",
    colorMuted: "oklch(0.955 0.008 80)",
    colorMutedForeground: "oklch(0.55 0.012 50)",
    borderRadius: "0.625rem",
    fontFamily: "var(--font-sans), system-ui, sans-serif",
  },
  elements: {
    rootBox: {
      width: "100%",
      maxWidth: "100%",
    },
    cardBox: {
      boxShadow: "none",
      width: "100%",
      backgroundColor: "transparent",
    },
    card: {
      backgroundColor: "transparent",
      boxShadow: "none",
      padding: "0",
      gap: "1rem",
      border: "none",
    },
    headerTitle: {
      color: "oklch(0.245 0.008 40)",
      fontSize: "1.5rem",
      fontWeight: "600",
      letterSpacing: "-0.02em",
    },
    headerSubtitle: {
      color: "oklch(0.55 0.012 50)",
    },
    socialButtonsBlockButton: {
      backgroundColor: "oklch(0.985 0.005 85)",
      color: "oklch(0.245 0.008 40)",
      border: "1px solid oklch(0.905 0.012 70)",
      boxShadow: "none",
    },
    socialButtonsBlockButtonText: {
      color: "oklch(0.245 0.008 40)",
      fontWeight: "500",
    },
    socialButtonsProviderIcon: {
      filter: "none",
    },
    lastAuthenticationStrategyBadge: {
      display: "none",
    },
    dividerLine: {
      backgroundColor: "oklch(0.905 0.012 70)",
    },
    dividerText: {
      color: "oklch(0.55 0.012 50)",
    },
    formFieldLabel: {
      color: "oklch(0.35 0.01 40)",
    },
    formFieldInput: {
      backgroundColor: "oklch(0.968 0.008 85)",
      color: "oklch(0.245 0.008 40)",
      borderColor: "oklch(0.905 0.012 70)",
    },
    formButtonPrimary: {
      backgroundColor: "oklch(0.4 0.135 25.8)",
      color: "oklch(0.985 0.006 85)",
      fontWeight: "500",
      textTransform: "none",
      boxShadow: "none",
    },
    footer: {
      backgroundColor: "transparent",
      background: "transparent",
    },
    footerAction: {
      backgroundColor: "transparent",
    },
    footerActionLink: {
      color: "oklch(0.4 0.135 25.8)",
      fontWeight: "500",
    },
    footerActionText: {
      color: "oklch(0.55 0.012 50)",
    },
    identityPreviewText: {
      color: "oklch(0.245 0.008 40)",
    },
    identityPreviewEditButton: {
      color: "oklch(0.55 0.012 50)",
    },
    formFieldInputShowPasswordButton: {
      color: "oklch(0.55 0.012 50)",
    },
    otpCodeFieldInput: {
      backgroundColor: "oklch(0.968 0.008 85)",
      color: "oklch(0.245 0.008 40)",
      borderColor: "oklch(0.905 0.012 70)",
    },
    formFieldHintText: {
      color: "oklch(0.55 0.012 50)",
    },
    formFieldSuccessText: {
      color: "oklch(0.55 0.12 155)",
    },
    formFieldErrorText: {
      color: "oklch(0.577 0.245 27.325)",
    },
    formFieldAction: {
      color: "oklch(0.4 0.135 25.8)",
    },
    formResendCodeLink: {
      color: "oklch(0.4 0.135 25.8)",
    },
    backLink: {
      color: "oklch(0.55 0.012 50)",
    },
    backRow: {
      color: "oklch(0.55 0.012 50)",
    },
    alternativeMethodsBlockButton: {
      backgroundColor: "oklch(0.985 0.005 85)",
      color: "oklch(0.245 0.008 40)",
      border: "1px solid oklch(0.905 0.012 70)",
    },
    alternativeMethodsBlockButtonText: {
      color: "oklch(0.245 0.008 40)",
    },
    main: {
      color: "oklch(0.245 0.008 40)",
      backgroundColor: "transparent",
    },
    scrollBox: {
      color: "oklch(0.245 0.008 40)",
      backgroundColor: "transparent",
    },
    alertText: {
      color: "oklch(0.245 0.008 40)",
    },
    logoBox: {
      display: "none",
    },
    navbar: {
      backgroundColor: "transparent",
    },
  },
}
