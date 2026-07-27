import type { Appearance } from "@clerk/types"

/** Clerk auth widgets — explicit colors (Tailwind classes don't apply inside Clerk). */
export const clerkAppearance: Appearance = {
  variables: {
    colorBackground: "oklch(0.205 0 0)",
    colorText: "oklch(0.985 0 0)",
    colorTextSecondary: "oklch(0.708 0 0)",
    colorInputBackground: "oklch(0.269 0 0)",
    colorInputText: "oklch(0.985 0 0)",
    colorPrimary: "oklch(0.985 0 0)",
    colorPrimaryForeground: "oklch(0.145 0 0)",
    colorNeutral: "oklch(0.269 0 0)",
    colorDanger: "oklch(0.704 0.191 22.216)",
    colorMuted: "oklch(0.269 0 0)",
    colorMutedForeground: "oklch(0.708 0 0)",
    borderRadius: "0.5rem",
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
    },
    card: {
      backgroundColor: "transparent",
      boxShadow: "none",
      padding: 0,
      gap: "1rem",
    },
    headerTitle: {
      color: "oklch(0.985 0 0)",
      fontSize: "1.5rem",
      fontWeight: "600",
    },
    headerSubtitle: {
      color: "oklch(0.708 0 0)",
    },
    socialButtonsBlockButton: {
      backgroundColor: "oklch(0.269 0 0)",
      color: "oklch(0.985 0 0)",
      border: "1px solid oklch(1 0 0 / 12%)",
    },
    socialButtonsBlockButtonText: {
      color: "oklch(0.985 0 0)",
      fontWeight: "500",
    },
    dividerLine: {
      backgroundColor: "oklch(1 0 0 / 12%)",
    },
    dividerText: {
      color: "oklch(0.708 0 0)",
    },
    formFieldLabel: {
      color: "oklch(0.85 0 0)",
    },
    formFieldInput: {
      backgroundColor: "oklch(0.269 0 0)",
      color: "oklch(0.985 0 0)",
      borderColor: "oklch(1 0 0 / 15%)",
    },
    formButtonPrimary: {
      backgroundColor: "oklch(0.985 0 0)",
      color: "oklch(0.145 0 0)",
      fontWeight: "500",
      textTransform: "none",
    },
    footerActionLink: {
      color: "oklch(0.985 0 0)",
    },
    footerActionText: {
      color: "oklch(0.708 0 0)",
    },
    identityPreviewText: {
      color: "oklch(0.985 0 0)",
    },
    identityPreviewEditButton: {
      color: "oklch(0.708 0 0)",
    },
    formFieldInputShowPasswordButton: {
      color: "oklch(0.708 0 0)",
    },
    otpCodeFieldInput: {
      backgroundColor: "oklch(0.269 0 0)",
      color: "oklch(0.985 0 0)",
      borderColor: "oklch(1 0 0 / 15%)",
    },
    formFieldHintText: {
      color: "oklch(0.708 0 0)",
    },
    formFieldSuccessText: {
      color: "oklch(0.696 0.17 162.48)",
    },
    formFieldErrorText: {
      color: "oklch(0.704 0.191 22.216)",
    },
    formFieldAction: {
      color: "oklch(0.985 0 0)",
    },
    formResendCodeLink: {
      color: "oklch(0.985 0 0)",
    },
    backLink: {
      color: "oklch(0.708 0 0)",
    },
    backRow: {
      color: "oklch(0.708 0 0)",
    },
    alternativeMethodsBlockButton: {
      backgroundColor: "oklch(0.269 0 0)",
      color: "oklch(0.985 0 0)",
      border: "1px solid oklch(1 0 0 / 12%)",
    },
    alternativeMethodsBlockButtonText: {
      color: "oklch(0.985 0 0)",
    },
    main: {
      color: "oklch(0.985 0 0)",
    },
    scrollBox: {
      color: "oklch(0.985 0 0)",
    },
    alertText: {
      color: "oklch(0.985 0 0)",
    },
    logoBox: {
      display: "none",
    },
  },
}
