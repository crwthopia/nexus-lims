import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { Login } from "./pages/Login";
import { SamplesList } from "./pages/SamplesList";
import { SampleDetail } from "./pages/SampleDetail";
import { ReviewQueue } from "./pages/ReviewQueue";
import { TestingQueue } from "./pages/TestingQueue";
import { TestRequestDetail } from "./pages/TestRequestDetail";
import { DocumentsList } from "./pages/DocumentsList";
import { DocumentDetail } from "./pages/DocumentDetail";
import { InvestigationsList } from "./pages/InvestigationsList";
import { InvestigationDetail } from "./pages/InvestigationDetail";
import { EquipmentList } from "./pages/EquipmentList";
import { InstrumentDetail } from "./pages/InstrumentDetail";
import { TrainingList } from "./pages/TrainingList";
import { TrainingSessionDetail } from "./pages/TrainingSessionDetail";
import { ReportsList } from "./pages/ReportsList";
import { BillingList } from "./pages/BillingList";
import { InvoiceDetail } from "./pages/InvoiceDetail";

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
        <Route path="/review-queue" element={<ReviewQueue />} />
        <Route path="/testing-queue" element={<TestingQueue />} />
        <Route path="/test-requests/:id" element={<TestRequestDetail />} />
        <Route path="/documents" element={<DocumentsList />} />
        <Route path="/documents/:id" element={<DocumentDetail />} />
        <Route path="/investigations" element={<InvestigationsList />} />
        <Route path="/investigations/:id" element={<InvestigationDetail />} />
        <Route path="/equipment" element={<EquipmentList />} />
        <Route path="/equipment/instruments/:id" element={<InstrumentDetail />} />
        <Route path="/training" element={<TrainingList />} />
        <Route path="/training-sessions/:id" element={<TrainingSessionDetail />} />
        <Route path="/reports" element={<ReportsList />} />
        <Route path="/billing" element={<BillingList />} />
        <Route path="/invoices/:id" element={<InvoiceDetail />} />
      </Route>
    </Routes>
  );
}

export default App;
