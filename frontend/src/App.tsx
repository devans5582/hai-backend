import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { AssessmentDetail } from "./pages/AssessmentDetail";
import { Dashboard } from "./pages/Dashboard";
import { NewAssessment } from "./pages/NewAssessment";
import { Ontology } from "./pages/Ontology";
import { OrganizationDetail, Organizations } from "./pages/Organizations";
import { Reviews } from "./pages/Reviews";
import { Settings } from "./pages/Settings";
import { Verify } from "./pages/Verify";
import { queryClient } from "./lib/query";

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="assessments/new" element={<NewAssessment />} />
        <Route path="assessments/:id" element={<AssessmentDetail />} />
        <Route path="reviews" element={<Reviews />} />
        <Route path="organizations" element={<Organizations />} />
        <Route path="organizations/:id" element={<OrganizationDetail />} />
        <Route path="ontology" element={<Ontology />} />
        <Route path="verify" element={<Verify />} />
        <Route path="settings" element={<Settings />} />
        <Route
          path="*"
          element={
            <div>
              <h1>Not found</h1>
              <p className="muted">No page at this address.</p>
            </div>
          }
        />
      </Route>
    </Routes>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
