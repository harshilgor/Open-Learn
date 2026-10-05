import type { Metadata } from "next";
import "./globals.css";
import { Toaster } from "@/components/ui/sonner";
import { ThemeProvider } from "@/components/theme-provider";
import { AccountAccess, AccountWorkspace } from '@/components/account-access';
import { AppInstall } from "@/components/app-install";

export const metadata: Metadata = {
  manifest: "/manifest.webmanifest",
  appleWebApp: { capable: true, title: "Open Learn", statusBarStyle: "default" },
  title: "Open Learn. — A space to understand",
  description: "Explore connected ideas and follow your curiosity without losing your place.",
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
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
          <AccountWorkspace>{children}</AccountWorkspace>
          <AccountAccess />
          <AppInstall />
          <Toaster />
        </ThemeProvider>
      </body>
    </html>
  );
}
