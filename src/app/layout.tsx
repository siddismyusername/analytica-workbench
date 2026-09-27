import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Analytica Workbench",
  description: "A professional data analysis workbench for preparation, statistics, modeling, and reproducible reporting.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
