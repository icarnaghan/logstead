import { Route, Routes } from "react-router-dom";
import AppLayout from "./components/AppLayout";
import DashboardPage from "./pages/DashboardPage";
import PropertiesPage from "./pages/PropertiesPage";
import TransactionsPage from "./pages/TransactionsPage";
import AssetsPage from "./pages/AssetsPage";
import ReportsPage from "./pages/ReportsPage";
import CombinedReportsPage from "./pages/CombinedReportsPage";
import ProfilePage from "./pages/ProfilePage";
import PropertyDetailPage from "./pages/PropertyDetailPage";
import PropertyLayout from "./components/PropertyLayout";
import NotFoundPage from "./pages/NotFoundPage";

/**
 * Root application component.
 *
 * Declares the route table and renders every route inside the shared
 * {@link AppLayout} shell. The property routes are nested under the
 * {@link PropertyLayout} layout route, which fetches the property once and
 * shares it (by name, never the raw id) with its child routes:
 * - `/`                                    Dashboard
 * - `/properties`                          Properties list
 * - `/reports`                             Combined portfolio Schedule E report
 * - `/properties/:propertyId`              Per-property detail (index)
 * - `/properties/:propertyId/transactions` Per-property transactions
 * - `/properties/:propertyId/assets`       Per-property depreciable assets
 * - `/properties/:propertyId/reports`      Per-property Schedule E report
 *
 * `BrowserRouter` is provided by `main.tsx`.
 */
export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<DashboardPage />} />
        <Route path="properties" element={<PropertiesPage />} />
        <Route path="reports" element={<CombinedReportsPage />} />
        <Route path="properties/:propertyId" element={<PropertyLayout />}>
          <Route index element={<PropertyDetailPage />} />
          <Route path="transactions" element={<TransactionsPage />} />
          <Route path="assets" element={<AssetsPage />} />
          <Route path="reports" element={<ReportsPage />} />
        </Route>
        <Route path="profile" element={<ProfilePage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
