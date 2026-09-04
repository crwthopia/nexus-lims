import { Navigate } from "react-router-dom";
import { useAuth, LOGIN_URL } from "../auth/context";
import { Logo } from "../components/Logo";

export function Login() {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) return null;
  if (isAuthenticated) return <Navigate to="/samples" replace />;

  return (
    <div className="container">
      <div className="card auth-card">
        <div style={{ display: "flex", justifyContent: "center", marginBottom: 6 }}>
          <h1 style={{ fontSize: "1.4rem", margin: 0 }}>
            <Logo />
          </h1>
        </div>
        <p style={{ color: "var(--color-text-muted)", margin: "0 0 24px" }}>Staff Console</p>
        <a href={LOGIN_URL} className="btn btn-primary" style={{ width: "100%", justifyContent: "center" }}>
          Log in with Microsoft
        </a>
      </div>
    </div>
  );
}
