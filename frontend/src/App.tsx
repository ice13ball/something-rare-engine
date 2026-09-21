// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { lazy, Suspense, useEffect, useState, useCallback } from "react";
import { BrowserRouter, Routes, Route, useLocation } from "react-router-dom";
import { HelmetProvider } from "react-helmet-async";
import { SEO } from "./components/SEO";
import { sendPageView } from "./utils/analytics";
import { Map3D } from "./components/Map3D";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { CookieBanner } from "./components/CookieBanner";
import { WelcomeOverlay } from "./components/WelcomeOverlay";
import { TutorialCoach } from "./components/TutorialCoach";
import { FooterLinks } from "./components/FooterLinks";
import { MobileMenuButton } from "./components/MobileMenuButton";
import { FeedbackModal } from "./components/FeedbackModal";
import { ReportToast } from "./components/ReportToast";
import { LayerLoadingProgress } from "./components/LayerLoadingProgress";
import { ExportPanel } from "./components/ExportPanel";

const LegalPage = lazy(() => import("./components/LegalPage").then(m => ({ default: m.LegalPage })));
const SeoPage = lazy(() => import("./components/SeoPage").then(m => ({ default: m.SeoPage })));
const ImpactReportV2 = lazy(() => import("./components/ImpactReportV2").then(m => ({ default: m.ImpactReportV2 })));
const ImpactReportV2Concession = lazy(() => import("./components/ImpactReportV2Concession").then(m => ({ default: m.ImpactReportV2Concession })));
const ReportRouter = lazy(() => import("./components/ReportRouter").then(m => ({ default: m.ReportRouter })));
const ClaimReportRedirect = lazy(() => import("./components/ReportRouter").then(m => ({ default: m.ClaimReportRedirect })));
const BlogListPage = lazy(() => import("./components/BlogListPage").then(m => ({ default: m.BlogListPage })));
const BlogArticlePage = lazy(() => import("./components/BlogArticlePage").then(m => ({ default: m.BlogArticlePage })));
const VentReport = lazy(() => import("./components/VentReport").then(m => ({ default: m.VentReport })));
const ChessReport = lazy(() => import("./components/ChessReport").then(m => ({ default: m.ChessReport })));
const ApiDocsPage = lazy(() => import("./components/ApiDocsPage").then(m => ({ default: m.ApiDocsPage })));

function MapApp() {
  const [consentOpen, setConsentOpen]   = useState(false);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const reopenConsent = useCallback(() => setConsentOpen(true), []);

  return (
    <>
      <SEO />
      <a href="#map-canvas" className="skip-nav">Skip to map</a>
      <main className="relative w-screen h-screen bg-page-bg overflow-hidden" style={{ touchAction: "none" }}>
        <h1 className="sr-only">Abyssal Claims — Interactive Environmental Map</h1>
        <ErrorBoundary>
          <Map3D />
        </ErrorBoundary>
        <FooterLinks onReopenConsent={reopenConsent} onOpenFeedback={() => setFeedbackOpen(true)} />
        <MobileMenuButton onReopenConsent={reopenConsent} onOpenFeedback={() => setFeedbackOpen(true)} />
        {feedbackOpen && <FeedbackModal onClose={() => setFeedbackOpen(false)} />}
        <LayerLoadingProgress />
        <ReportToast />
        <CookieBanner forceOpen={consentOpen} />
        <WelcomeOverlay />
        <TutorialCoach />
        <ExportPanel />
      </main>
    </>
  );
}

function PageLoader() {
  return (
    <div className="min-h-screen bg-[#0a0e14] flex items-center justify-center">
      <p className="text-white/70 animate-pulse">Loading...</p>
    </div>
  );
}

function PageViewBeacon() {
  const location = useLocation();
  useEffect(() => { sendPageView(location.pathname); }, [location.pathname]);
  return null;
}

export default function App() {
  return (
    <HelmetProvider>
      <BrowserRouter>
        <PageViewBeacon />
        <Routes>
          <Route path="/" element={<MapApp />} />
          <Route path="/privacy" element={<Suspense fallback={<PageLoader />}><LegalPage /></Suspense>} />
          <Route path="/terms" element={<Suspense fallback={<PageLoader />}><LegalPage /></Suspense>} />
          <Route path="/about" element={<Suspense fallback={<PageLoader />}><LegalPage /></Suspense>} />
          <Route path="/concession/:id" element={<Suspense fallback={<PageLoader />}><SeoPage type="concession" /></Suspense>} />
          <Route path="/vent/:id" element={<Suspense fallback={<PageLoader />}><SeoPage type="vent" /></Suspense>} />
          <Route path="/seamount/:id" element={<Suspense fallback={<PageLoader />}><SeoPage type="seamount" /></Suspense>} />
          <Route path="/report/:platformId" element={<Suspense fallback={<PageLoader />}><ReportRouter /></Suspense>} />
          <Route path="/report/v2/argo/:platformId" element={<Suspense fallback={<PageLoader />}><ImpactReportV2 /></Suspense>} />
          <Route path="/report/v2/concession/:isaId" element={<Suspense fallback={<PageLoader />}><ImpactReportV2Concession /></Suspense>} />
          <Route path="/claim-report/:isaId" element={<Suspense fallback={<PageLoader />}><ClaimReportRedirect /></Suspense>} />
          <Route path="/vent-report/:ventId" element={<Suspense fallback={<PageLoader />}><VentReport /></Suspense>} />
          <Route path="/chess-report/:locality" element={<Suspense fallback={<PageLoader />}><ChessReport /></Suspense>} />
          <Route path="/blog" element={<Suspense fallback={<PageLoader />}><BlogListPage /></Suspense>} />
          <Route path="/blog/:slug" element={<Suspense fallback={<PageLoader />}><BlogArticlePage /></Suspense>} />
          <Route path="/api-docs" element={<Suspense fallback={<PageLoader />}><ApiDocsPage /></Suspense>} />
        </Routes>
      </BrowserRouter>
    </HelmetProvider>
  );
}
