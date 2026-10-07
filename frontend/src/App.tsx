import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { ErrorBoundary } from "@/components/ErrorBoundary";
import { Spinner } from "@/components/ui/states";
import AppLayout from "@/layouts/AppLayout";
import LandingPage from "@/pages/LandingPage";

// Heavy pages (React Flow, charts, tables) load on demand.
const DashboardPage = lazy(() => import("@/pages/DashboardPage"));
const RunsPage = lazy(() => import("@/pages/RunsPage"));
const NewRunPage = lazy(() => import("@/pages/NewRunPage"));
const RunPage = lazy(() => import("@/pages/RunPage"));
const BugsPage = lazy(() => import("@/pages/BugsPage"));
const BugDetailPage = lazy(() => import("@/pages/BugDetailPage"));
const ExplorerPage = lazy(() => import("@/pages/ExplorerPage"));
const ProjectsPage = lazy(() => import("@/pages/ProjectsPage"));
const ProjectDetailPage = lazy(() => import("@/pages/ProjectDetailPage"));
const SettingsPage = lazy(() => import("@/pages/SettingsPage"));

export default function App() {
  return (
    <ErrorBoundary>
      <Suspense fallback={<Spinner />}>
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route element={<AppLayout />}>
            <Route path="dashboard" element={<DashboardPage />} />
            <Route path="runs" element={<RunsPage />} />
            <Route path="runs/new" element={<NewRunPage />} />
            <Route path="runs/:runId" element={<RunPage />} />
            <Route path="bugs" element={<BugsPage />} />
            <Route path="bugs/:bugId" element={<BugDetailPage />} />
            <Route path="explorer" element={<ExplorerPage />} />
            <Route path="projects" element={<ProjectsPage />} />
            <Route path="projects/:projectId" element={<ProjectDetailPage />} />
            <Route path="settings" element={<SettingsPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </ErrorBoundary>
  );
}
