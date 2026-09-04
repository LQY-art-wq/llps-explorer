import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "LLPS Explorer · Analysis Workspace",
  description: "Sequence-based Phase Separation Prediction & Interpretation. A scientific analysis workspace with explicit method provenance.",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
