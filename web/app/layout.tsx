import type { Metadata } from "next";
import "@fontsource-variable/inter";
import "./globals.css";
import "./design-system.css";
import { Toaster } from "@/components/ui/sonner";
import { ThemeProvider } from "@/components/theme-provider";
import { AccountAccess, AccountWorkspace } from '@/components/account-access';
import { AppInstall } from "@/components/app-install";
import { SourcePassageDialog } from "@/components/source-passage-dialog";

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "https://open-learn-eta.vercel.app"),
  manifest: "/manifest.webmanifest",
  appleWebApp: { capable: true, title: "Open Learn", statusBarStyle: "default" },
  title: "Open Learn — Your AI study partner",
  description: "Ask a question, choose how deeply to explore, then save the explanations that click as notes, reviews, and quizzes.",
  openGraph: {
    type: "website",
    locale: "en_US",
    siteName: "Open Learn",
    title: "Open Learn — Your AI study partner",
    description: "Explore ideas at your pace. Keep the explanations, notes, and reviews that help them stick.",
    images: [{ url: "/opengraph-image", width: 1200, height: 630, alt: "Open Learn, a study partner for curious minds" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "Open Learn — Your AI study partner",
    description: "Explore ideas at your pace. Keep the explanations, notes, and reviews that help them stick.",
    images: ["/opengraph-image"],
  },
  other: {
    "codex-preview": "development",
  },
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
    apple: "/app-icon-192.png",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="antialiased" suppressHydrationWarning>
        <ThemeProvider attribute="class" defaultTheme="light" enableSystem disableTransitionOnChange>
          <AccountWorkspace>{children}</AccountWorkspace>
          <AccountAccess />
          <AppInstall />
          <SourcePassageDialog />
          <Toaster />
        </ThemeProvider>
      </body>
    </html>
  );
}
