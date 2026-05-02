// @vitest-environment jsdom
import { it } from "vitest";
import { render } from "@testing-library/react";
import { ResumeJobBanner } from "@/components/ResumeJobBanner";

it("debug", () => {
  const { container } = render(
    <ResumeJobBanner
      pendingResume={{ jobId: "abc12345", cacheKey: "c", criteria: { make: "Toyota", budget_usd: 15000 }, startedAt: Date.now() }}
      validationErrors={[]}
      onResume={() => {}}
      onDismiss={() => {}}
      onClearErrors={() => {}}
    />,
  );
  console.log(container.innerHTML);
});
