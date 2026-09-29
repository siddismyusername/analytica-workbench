import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./layers.css";
import "@heroui/styles/css";

import "./globals.css";
import "./design-system.css";
import { Providers } from "./providers";

const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-inter",
});

export const metadata: Metadata = {
  title: "Analytica Workbench",
  description: "A professional data analysis workbench for preparation, statistics, modeling, and reproducible reporting.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={inter.variable} suppressHydrationWarning>
      <body><Providers>{children}</Providers></body>
    </html>
  );
}
