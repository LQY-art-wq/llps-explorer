import { Workspace } from "@/components/workspace";

export const dynamic = 'force-dynamic';

export default function Home() {
  return <Workspace testMode={process.env.FEATURE_VIEWER_TEST_MODE === '1'} />;
}
