import { notFound } from "next/navigation";
import { FeatureViewerFixture } from "@/components/feature-viewer-fixture";
import { featureViewerTestEnabled } from "@/lib/feature-test-fixtures";

// The flag is evaluated for each server request, including after a production build.
export const dynamic = "force-dynamic";

export default function FeatureViewerTestPage() {
  if (!featureViewerTestEnabled(process.env.FEATURE_VIEWER_TEST_MODE)) notFound();
  return <FeatureViewerFixture />;
}
