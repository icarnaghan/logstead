import { Route, Routes } from "react-router-dom";
import AppLayout from "./components/AppLayout";
import DashboardPage from "./pages/DashboardPage";
import PropertiesPage from "./pages/PropertiesPage";
import TransactionsPage from "./pages/TransactionsPage";
import AssetsPage from "./pages/AssetsPage";
import ReportsPage from "./pages/ReportsPage";
import ProfilePage from "./pages/ProfilePage";
import PropertyDetailPage from "./pages/PropertyDetailPage";
import NotFoundPage from "./pages/NotFoundPage";

/**
 * Root application component.
 *
 * Declares the route table and renders every route inside the shared
 * {@link AppLayout} shell. The routes are:
 * - `/`                                    Dashboard
 * - `/properties`                          Properties list
 * - `/properties/:propertyId/transactions` Per-property transactions
 * - `/properties/:propertyId/assets`       Per-property depreciable assets
 * - `/properties/:propertyId/reports`      Per-property Schedule E report
 *
 * The feature pages are stubs here; the real implementations arrive in tasks
 * 21–24. `BrowserRouter` is provided by `main.tsx`.
 */
export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<DashboardPage />} />
        <Route path="properties" element={<PropertiesPage />} />
        <Route
          path="properties/:propertyId"
          element={<PropertyDetailPage />}
        />
        <Route
          path="properties/:propertyId/transactions"
          element={<TransactionsPage />}
        />
        <Route
          path="properties/:propertyId/assets"
          element={<AssetsPage />}
        />
        <Route
          path="properties/:propertyId/reports"
          element={<ReportsPage />}
        />
        <Route path="profile" element={<ProfilePage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
