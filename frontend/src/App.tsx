import { useRoutes } from "react-router-dom";
import { APP_ROUTES } from "./routes";

/**
 * Root application component.
 *
 * Renders the route table declared in `routes.tsx` (see the doc comment on
 * {@link APP_ROUTES} for the full list). `BrowserRouter` is provided by
 * `main.tsx`.
 */
export default function App() {
  return useRoutes(APP_ROUTES);
}
