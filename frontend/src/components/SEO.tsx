// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import { Helmet } from "react-helmet-async";
import siteGraph from "../../seo/site-graph.json";

const SITE_URL = "https://something-rare.com";
const OG_IMAGE = `${SITE_URL}/og.jpg`;

const TITLE = "Abyssal Claims | Ocean & Land Environmental Map";
const DESCRIPTION =
  "Interactive 3D map tracking 50+ environmental data layers across ocean and land. Deep-sea mining concessions, global mining footprints, deforestation, active fires, air quality, biodiversity hotspots, hydrothermal vents, and real-time monitoring — powered by ISA, OBIS, NASA FIRMS, OpenAQ, WRI, and more.";
const KEYWORDS =
  "deep sea mining, ISA mining concessions, international seabed authority, polymetallic nodules, hydrothermal vents, InterRidge vents database, seamounts, ocean conservation, marine biodiversity, Argo floats, ocean monitoring, OBIS biodiversity, environmental map, deforestation, tree cover loss, global forest watch, mining footprints, active fires, NASA FIRMS, air quality, OpenAQ, PM2.5, tailings dams, landslides, surface water, soil carbon, carbon flux, environmental transparency, ocean and land, 3D globe";

const JSON_LD = JSON.stringify(siteGraph);

export function SEO() {
  return (
    <Helmet>
      <title>{TITLE}</title>
      <meta name="description" content={DESCRIPTION} />
      <meta name="keywords" content={KEYWORDS} />
      <link rel="canonical" href={SITE_URL} />

      {/* Open Graph */}
      <meta property="og:site_name" content="Abyssal Claims" />
      <meta property="og:title" content={TITLE} />
      <meta property="og:description" content={DESCRIPTION} />
      <meta property="og:type" content="website" />
      <meta property="og:url" content={SITE_URL} />
      <meta property="og:image" content={OG_IMAGE} />
      <meta property="og:image:width" content="1200" />
      <meta property="og:image:height" content="630" />
      <meta property="og:image:alt" content="3D globe showing ocean and land environmental data layers" />
      <meta property="og:locale" content="en_US" />

      {/* Twitter */}
      <meta name="twitter:card" content="summary_large_image" />
      <meta name="twitter:title" content={TITLE} />
      <meta name="twitter:description" content={DESCRIPTION} />
      <meta name="twitter:image" content={OG_IMAGE} />
      <meta name="twitter:image:alt" content="3D globe showing ocean and land environmental data layers" />

      {/* Google Scholar / Highwire Press citation tags */}
      <meta name="citation_title" content="Abyssal Claims: Ocean & Land Environmental Transparency Map" />
      <meta name="citation_author" content="Mazurowski, Michal" />
      <meta name="citation_author_orcid" content="https://orcid.org/0009-0007-3786-0310" />
      <meta name="citation_doi" content="10.5281/zenodo.19745884" />
      <meta name="citation_publication_date" content="2026" />
      <meta name="citation_publisher" content="Zenodo" />
      <meta name="citation_public_url" content={SITE_URL} />

      {/* Structured data */}
      <script type="application/ld+json">{JSON_LD}</script>
    </Helmet>
  );
}
