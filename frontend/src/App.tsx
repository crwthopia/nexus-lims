import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { Login } from "./pages/Login";
import { SamplesList } from "./pages/SamplesList";
import { SampleDetail } from "./pages/SampleDetail";

function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        <Route path="/" element={<Navigate to="/samples" replace />} />
        <Route path="/samples" element={<SamplesList />} />
        <Route path="/samples/:id" element={<SampleDetail />} />
      </Route>
    </Routes>
  );
}

export default App;
