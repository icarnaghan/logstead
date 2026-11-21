import { Navigate, type RouteObject } from "react-router-dom";
import AppLayout from "./components/AppLayout";
import DashboardPage from "./pages/DashboardPage";
import PropertiesPage from "./pages/PropertiesPage";
import BusinessesPage from "./pages/BusinessesPage";
import BusinessDetailPage from "./pages/BusinessDetailPage";
import TransactionsPage from "./pages/TransactionsPage";
import RepairsPage from "./pages/RepairsPage";
import AssetsPage from "./pages/AssetsPage";
import LoansPage from "./pages/LoansPage";
import ReportsPage from "./pages/ReportsPage";
import YearEndChecklistPage from "./pages/YearEndChecklistPage";
import CombinedReportsPage from "./pages/CombinedReportsPage";
import AccountantPackagePage from "./pages/AccountantPackagePage";
import ImportsLayout from "./pages/ImportsLayout";
import ScheduleEImportPage from "./pages/ScheduleEImportPage";
import ScheduleEExtractionPage from "./pages/ScheduleEExtractionPage";
import CarryforwardPage from "./pages/CarryforwardPage";
import ActivityPage from "./pages/ActivityPage";
import SearchPage from "./pages/SearchPage";
import ProfilePage from "./pages/ProfilePage";
import PropertyDetailPage from "./pages/PropertyDetailPage";
import PropertyLayout from "./components/PropertyLayout";
import NotFoundPage from "./pages/NotFoundPage";

/**
 * Application route table.
 *
 * Every route renders inside the shared {@link AppLayout} shell. The property
 * routes are nested under the {@link PropertyLayout} layout route, which
 * fetches the property once and shares it (by name, never the raw id) with
 * its child routes:
 * - `/`                                    Dashboard
 * - `/properties`                          Properties list
 * - `/businesses`                          Businesses list
 * - `/businesses/:businessId`              Per-business detail
 * - `/reports`                             Combined portfolio Schedule E report
 * - `/carryforward`                        Carryforward reconciliation
 * - `/accountant-package`                 Accountant package (ZIP for a tax year)
 * - `/imports`                             Redirects to `/imports/schedule-e`
 * - `/imports/schedule-e`                  Imports tab: guided Schedule E import (manual)
 * - `/imports/schedule-e/extract`          Imports tab: Schedule E import from a PDF
 *
 * The two `/imports/*` pages are tabs rendered inside the {@link ImportsLayout}
 * layout route, which owns the page heading and the tab bar.
 * - `/properties/:propertyId`              Per-property detail (index)
 * - `/properties/:propertyId/transactions` Per-property transactions
 * - `/properties/:propertyId/repairs`      Per-property repairs and itemized expenses
 * - `/properties/:propertyId/assets`       Per-property depreciable assets
 * - `/properties/:propertyId/loans`        Per-property mortgage loans
 * - `/properties/:propertyId/reports`      Per-property Schedule E report
 * - `/properties/:propertyId/checklist`   Per-property Year-end checklist
 * - `/activity`                            Activity history (`?property=` filter)
 * - `/search`                              Search (`?q=` text)
 * - `/profile`                             Profile
 * - `*`                                    Not found
 *
 * Redirect-only routes carry `handle: { redirect: true }` so {@link leafPaths}
 * skips them.
 */
export const APP_ROUTES: RouteObject[] = [
  {
    element: <AppLayout />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: "properties", element: <PropertiesPage /> },
      { path: "businesses", element: <BusinessesPage /> },
      { path: "businesses/:businessId", element: <BusinessDetailPage /> },
      { path: "reports", element: <CombinedReportsPage /> },
      { path: "carryforward", element: <CarryforwardPage /> },
      { path: "accountant-package", element: <AccountantPackagePage /> },
      {
        path: "imports",
        element: <ImportsLayout />,
        children: [
          {
            index: true,
            element: <Navigate to="/imports/schedule-e" replace />,
            handle: { redirect: true },
          },
          { path: "schedule-e", element: <ScheduleEImportPage /> },
          {
            path: "schedule-e/extract",
            element: <ScheduleEExtractionPage />,
          },
        ],
      },
      {
        path: "properties/:propertyId",
        element: <PropertyLayout />,
        children: [
          { index: true, element: <PropertyDetailPage /> },
          { path: "transactions", element: <TransactionsPage /> },
          { path: "repairs", element: <RepairsPage /> },
          { path: "assets", element: <AssetsPage /> },
          { path: "loans", element: <LoansPage /> },
          { path: "reports", element: <ReportsPage /> },
          { path: "checklist", element: <YearEndChecklistPage /> },
        ],
      },
      { path: "activity", element: <ActivityPage /> },
      { path: "search", element: <SearchPage /> },
      { path: "profile", element: <ProfilePage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];

function isRedirect(route: RouteObject): boolean {
  const handle = route.handle as { redirect?: boolean } | undefined;
  return handle?.redirect === true;
}

function joinPath(base: string, segment: string | undefined): string {
  if (!segment) return base || "/";
  const joined = `${base.replace(/\/+$/, "")}/${segment.replace(/^\/+/, "")}`;
  return joined || "/";
}

/**
 * Returns the full path of every renderable leaf route in `routes`.
 *
 * Pathless layout routes and layout routes with children contribute their
 * path prefix only; index routes yield their parent's path. Routes marked
 * `handle: { redirect: true }` are skipped. Parameters (`:id`) and the
 * catch-all (`*`) are returned as written.
 */
export function leafPaths(routes: RouteObject[], base = ""): string[] {
  const out: string[] = [];
  for (const route of routes) {
    if (isRedirect(route)) continue;
    const path = route.index ? joinPath(base, undefined) : joinPath(base, route.path);
    if (route.children && route.children.length > 0) {
      out.push(...leafPaths(route.children, route.path ? path : base));
    } else {
      out.push(path);
    }
  }
  return out;
}
