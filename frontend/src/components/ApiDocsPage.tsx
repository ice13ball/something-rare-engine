// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { Helmet } from "react-helmet-async";
import { ApiReferenceReact } from "@scalar/api-reference-react";
import "@scalar/api-reference-react/style.css";

// Try-it calls hit the real API origin directly (NOT the /api BFF proxy, which
// force-sets the internal key). The user pastes their own X-API-Key, so their
// real key + quota are exercised. The site origin is whitelisted in backend CORS.
const OPENAPI_URL = "https://apiv2.something-rare.com/openapi.json";

export function ApiDocsPage() {
  return (
    <div style={{ height: "100vh", width: "100vw", overflow: "auto" }}>
      {/* Per-route canonical, same pattern as LegalPage/SeoPage/BlogListPage.
          index.html deliberately carries NO static canonical (see the comment
          there — fixed 2026-07-24) — react-helmet-async does not remove static
          tags, so a hardcoded one made every non-SSR route declare itself a
          duplicate of "/". This page had no <Helmet> at all, so it was the one
          route with no title, description or canonical. */}
      <Helmet>
        <title>API Documentation | Abyssal Claims</title>
        <meta
          name="description"
          content="REST API for Abyssal Claims: ISA mining concessions, hydrothermal vents, biodiversity, ocean chemistry and land layers. Requires an organisation-issued API key."
        />
        <link rel="canonical" href="https://something-rare.com/api-docs" />
      </Helmet>
      <ApiReferenceReact
        configuration={{
          url: OPENAPI_URL,
          theme: "deepSpace",
          darkMode: true,
        }}
      />
    </div>
  );
}
