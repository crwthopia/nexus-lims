import { Navigate } from "react-router-dom";
import { useAuth, LOGIN_URL } from "../auth/context";

export function Login() {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) return null;
  if (isAuthenticated) return <Navigate to="/samples" replace />;

  return (
    <div style={{ display: "grid", placeItems: "center", minHeight: "80vh" }}>
      <div className="card" style={{ padding: 40, width: 360, textAlign: "center" }}>
        <h1 style={{ fontSize: "1.4rem", margin: "0 0 4px" }}>NASAT LIMS</h1>
        <p style={{ color: "var(--color-text-muted)", margin: "0 0 24px" }}>Staff Console</p>
        <a href={LOGIN_URL} className="btn btn-primary" style={{ width: "100%", justifyContent: "center" }}>
          Log in with Microsoft
        </a>
      </div>
    </div>
  );
}
