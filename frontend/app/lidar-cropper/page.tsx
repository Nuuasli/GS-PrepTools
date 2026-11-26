import type { Metadata } from "next";
import LidarWorkspace from "./workspace";

export const metadata: Metadata = { title: "LiDAR Cropper | GS-PrepTools" };

export default function LidarCropperPage() {
  return <LidarWorkspace />;
}
