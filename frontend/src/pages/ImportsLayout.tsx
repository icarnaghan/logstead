import { useMemo, useState } from "react";
import { Outlet } from "react-router-dom";
import { ImportSectionTabs } from "../components/ImportSectionTabs";
import { PageHeader } from "../components/ui";
import { ImportsDirtyContext, useBeforeUnloadWhen } from "../lib/importsDirty";
import { useRegisterDirty } from "../lib/navigationGuard";
import { useDocumentTitle } from "../lib/useDocumentTitle";

/**
 * Layout route for the Imports section: single page heading, the import
 * method tabs, and the active tab's page via `Outlet`. Provides the dirty
 * context used to guard tab switches and page unloads.
 */
export default function ImportsLayout() {
  useDocumentTitle("Import Schedule E");
  const [dirty, setDirty] = useState(false);
  const value = useMemo(() => ({ dirty, setDirty }), [dirty]);
  useBeforeUnloadWhen(dirty);
  useRegisterDirty("imports", dirty);

  return (
    <ImportsDirtyContext.Provider value={value}>
      <section aria-labelledby="page-heading">
        <PageHeader title="Import Schedule E" />
        <ImportSectionTabs />
        <div className="mt-6">
          <Outlet />
        </div>
      </section>
    </ImportsDirtyContext.Provider>
  );
}
