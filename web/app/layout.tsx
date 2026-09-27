import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "pre-mortem — your deploy history, argued back at you",
  description:
    "A change-risk agent that recalls what your org's own past launches did, cites the precedent, and names the one detail that flips the outcome.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
