import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "BOUNDARY Status",
  description: "Local AMD agent development status",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
