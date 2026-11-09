import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../lib/auth";

/** Workspace routes: without credentials, go to sign-in and come back afterwards. */
export function RequireAuth() {
  const { authenticated } = useAuth();
  const location = useLocation();
  if (!authenticated) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  return <Outlet />;
}

/** Sign-in and sign-up: a signed-in user is sent to the workspace instead. */
export function RedirectIfAuthenticated() {
  const { authenticated } = useAuth();
  const location = useLocation();
  const params = new URLSearchParams(location.search);
  // An invitation or reset link must still open even while another session is stored in this browser.
  if (authenticated && !params.get("token")) return <Navigate to="/" replace />;
  return <Outlet />;
}
