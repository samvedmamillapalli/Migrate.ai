export const NAV_LINKS = [
  { label: "How it works", href: "/#prediction-learning" },
  {
    label: "Github",
    href: "https://github.com/samvedmamillapalli/Migrate.ai",
    external: true,
  },
  { label: "Our Journey", href: "/our-journey" },
] as const

export const GITHUB_URL = "https://github.com/samvedmamillapalli/Migrate.ai"

export const PIPELINE_STEPS = [
  {
    title: "Policy Checks",
    description: "Validate controls and guardrails.",
    icon: "shield",
  },
  {
    title: "Memory Retrieval",
    description: "Recall similar migrations.",
    icon: "database",
  },
  {
    title: "AI Prediction",
    description: "Forecast risks and paths.",
    icon: "blocks",
  },
  {
    title: "Human Approval",
    description: "Review with context.",
    icon: "check",
  },
  {
    title: "Shadow Execution",
    description: "Run safely in parallel.",
    icon: "branch",
  },
  {
    title: "Grade and Learn",
    description: "Improve every run.",
    icon: "blocks",
  },
] as const

export const TECHNOLOGIES = [
  "CockroachDB",
  "Amazon Bedrock",
  "Amazon Titan",
  "AWS Step Functions",
  "Amazon EventBridge",
] as const
export const JOURNAL_ENTRIES = [
  {
    date: "Jul 2026",
    readTime: "5 min read",
    title: "Why Database Migrations Are Scarier Than They Look",
    excerpt:
      "The hidden risks, cascading failures, and why a single SQL script can bring production to a halt.",
    href: "https://medium.com/@khurana.samrita/why-database-migrations-are-scarier-than-they-look-8afe463beb22",
    image:
      "https://framerusercontent.com/images/V2Q3fHX9Y47CEIkxwycTucBz7c.webp?width=1200&height=675",
    alt: "Night architecture and data light",
  },
  {
    date: "Jul 2026",
    readTime: "6 min read",
    title: "How Do You Know Whether the AI Was Right?",
    excerpt:
      "The reasons why we created a Shadow Execution Engine.",
    href: "https://medium.com/@khurana.samrita/how-do-you-know-whether-the-ai-was-right-a283e894d614",
    image:
      "https://framerusercontent.com/images/hgfcP3qv3L6nSUbzAaMPNlFrZb0.jpeg?width=1600&height=1066",
    alt: "Layered paper architecture",
  },
  {
    date: "Aug 2026",
    readTime: "6 min read",
    title: "Teaching AI to Learn From Real Database Migrations",
    excerpt:
      "Every verified migration becomes experience that improves the next prediction.",
    href: "https://medium.com/@khurana.samrita/teaching-ai-to-learn-from-real-database-migrations-6cc25178154d",
    image:
      "https://framerusercontent.com/images/r3vFerkhEm68IKC9ghTna7IV8.jpg?width=1600&height=900",
    alt: "Abstract luminous data field",
  },
  {
    date: "Aug 2026",
    readTime: "3 min read",
    title: "Building an AI System That Doesn't Trust AI",
    excerpt:
      "Why every AI decision should be verified before anyone trusts it.",
    href: "https://medium.com/@khurana.samrita/building-an-ai-system-that-doesnt-trust-ai-18489d9d33f7",
    image:
      "https://miro.medium.com/v2/resize:fit:1400/format:webp/0*VqxwveHRQP8QONYA",
    alt: "AI verification and trust architecture",
  },
  {
    date: "Aug 2026",
    readTime: "7 min read",
    title: "The Cluster Cleanup Problem",
    excerpt:
      "Why temporary infrastructure can quietly become one of the biggest operational costs.",
    href: "https://medium.com/@samvedmamillapalli/the-cluster-cleanup-problem-6fb835139094",
    image:
      "https://miro.medium.com/v2/resize:fit:1400/format:webp/1*2s3pFlNj4lOzfSlr2x1kzQ.png",
    alt: "Cloud clusters and infrastructure cleanup",
  },
] as const;