import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import App from "./App.tsx";
import AuthCallback from "./auth/AuthCallback.tsx";
import RequireAuth from "./auth/RequireAuth.tsx";
import { ThemeProvider } from "./theme/ThemeProvider.tsx";
import { ToastProvider } from "./components/ui/toast/ToastProvider.tsx";
import "./index.css";

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Root element #root not found");
}

createRoot(rootElement).render(
  <StrictMode>
    <ThemeProvider>
      <ToastProvider>
      <BrowserRouter>
      <Routes>
        {/* Hosted UI redirect target: exchanges the code, then lands on "/". */}
        <Route path="/auth/callback" element={<AuthCallback />} />
        {/* Everything else requires an authenticated session. */}
        <Route
          path="/*"
          element={
            <RequireAuth>
              <App />
            </RequireAuth>
          }
        />
      </Routes>
      </BrowserRouter>
      </ToastProvider>
    </ThemeProvider>
  </StrictMode>,
);
