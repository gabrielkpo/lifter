import { ImageResponse } from "next/og";
import Mark from "@/components/Mark";

// App icons for the manifest, drawn at build time: the kettlebell mark on the app's black.
const SIZES = ["192", "512"];

export const dynamicParams = false;

export function generateStaticParams() {
  return SIZES.map((size) => ({ size }));
}

export async function GET(_request: Request, { params }: { params: Promise<{ size: string }> }) {
  const size = Number((await params).size);
  return new ImageResponse(<Mark size={size} />, { width: size, height: size });
}
