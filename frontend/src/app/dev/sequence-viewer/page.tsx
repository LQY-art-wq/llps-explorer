import { notFound } from "next/navigation";
import { SequenceViewerFixture } from "@/components/sequence-viewer-fixture";
import { featureViewerTestEnabled } from "@/lib/feature-test-fixtures";

// The private server-side flag is checked for every request after a production build.
export const dynamic = "force-dynamic";

export default function SequenceViewerTestPage() {
  if (!featureViewerTestEnabled(process.env.FEATURE_VIEWER_TEST_MODE)) notFound();
  return <SequenceViewerFixture />;
}
