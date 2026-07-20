import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "BOUNDARY Control Center",
  description: "AI That Asks Before It Acts — local workflow control center",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
