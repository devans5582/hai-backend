import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { RedirectIfAuthenticated, RequireAuth } from "./components/Gate";
import { Layout } from "./components/Layout";
import { PublicLayout } from "./components/PublicLayout";
import { AssessmentDetail } from "./pages/AssessmentDetail";
import { Dashboard } from "./pages/Dashboard";
import { Login } from "./pages/Login";
import { NewAssessment } from "./pages/NewAssessment";
import { Ontology } from "./pages/Ontology";
import { OrganizationDetail, Organizations } from "./pages/Organizations";
import { Reviews } from "./pages/Reviews";
import { Settings } from "./pages/Settings";
import { Signup } from "./pages/Signup";
import { Team } from "./pages/Team";
import { Verify } from "./pages/Verify";
import { useAuth } from "./lib/auth";
import { queryClient } from "./lib/query";

/** Certificate verification is public: it renders inside the workspace when signed in, otherwise in the public shell. */
function VerifyShell() {
  const { authenticated } = useAuth();
  return authenticated ? <Layout /> : <PublicLayout />;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<RedirectIfAuthenticated />}>
        <Route element={<PublicLayout />}>
          <Route path="login" element={<Login />} />
          <Route path="signup" element={<Signup />} />
        </Route>
      </Route>
      <Route element={<VerifyShell />}>
        <Route path="verify" element={<Verify />} />
      </Route>
      <Route element={<RequireAuth />}>
        <Route element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="assessments/new" element={<NewAssessment />} />
          <Route path="assessments/:id" element={<AssessmentDetail />} />
          <Route path="reviews" element={<Reviews />} />
          <Route path="organizations" element={<Organizations />} />
          <Route path="organizations/:id" element={<OrganizationDetail />} />
          <Route path="team" element={<Team />} />
          <Route path="ontology" element={<Ontology />} />
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
