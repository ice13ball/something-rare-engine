// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

export const CONTACT_EMAIL = "m.mazurowski@ai-wall.com";
export const SITE_NAME = "Abyssal Claims";
export const SITE_URL = "https://something-rare.com";

export interface LegalSection {
  heading: string;
  id?: string;
  paragraphs: (string | { list: string[] } | { code: string })[];
}

// ⛔ TWO Zenodo records, and swapping them is a licence error, not a typo.
//
//   CODE_DOI — the engine that runs this platform. Resource type "Software",
//              AGPL-3.0-or-later, v1.0.0, minted 2026-09-12 when the mirror
//              `ice13ball/something-rare-engine` went public.
//   DOCS_DOI — the methods and data documentation. Resource type "Software
//              documentation", CC-BY-4.0, version 1.6.
//
// The software record's own Zenodo metadata carries `isDocumentedBy` pointing
// at the documentation record: they are two halves of one pair. Cite the
// documentation for the METHOD and the code record for the CODE. Putting the
// documentation's DOI beside the words "the software is licensed AGPL" — which
// this file did until 2026-09-15 — attaches a CC-BY licence to AGPL software
// on the page people copy citations from.
//
// 📌 Both are CONCEPT DOIs: they always resolve to the newest version, which
// is what a citation should point at. Version DOIs (…22728477, …21684359) are
// for pinning an exact release.
export const CODE_DOI = "10.5281/zenodo.22728476";
export const CODE_DOI_URL = "https://doi.org/10.5281/zenodo.22728476";
export const CODE_ZENODO_URL = "https://zenodo.org/records/22728476";
export const CODE_TITLE =
  "Abyssal Claims: source code of a FAIR-aligned integration platform for deep-sea and terrestrial mining transparency";
export const CODE_VERSION = "v1.0.0";
export const CODE_LICENCE = "AGPL-3.0-or-later";

export const DOCS_DOI = "10.5281/zenodo.19745884";
export const DOCS_DOI_URL = "https://doi.org/10.5281/zenodo.19745884";
export const DOCS_ZENODO_URL = "https://zenodo.org/records/19745884";
export const DOCS_TITLE =
  "Abyssal Claims: A FAIR-aligned integration platform for deep-sea and terrestrial mining transparency";
export const DOCS_VERSION = "1.6";
export const DOCS_LICENCE = "CC-BY-4.0";
export const ORCID = "0009-0007-3786-0310";
export const ORCID_URL = "https://orcid.org/0009-0007-3786-0310";
export const AUTHOR_NAME = "Michal Mazurowski";

export interface LegalDoc {
  title: string;
  updated: string;
  sections: LegalSection[];
}

export const PRIVACY_POLICY: LegalDoc = {
  title: "Privacy Policy",
  updated: "April 2026",
  sections: [
    {
      heading: "Who We Are",
      paragraphs: [
        `${SITE_NAME} is an interactive map visualising international deep-sea mining concessions issued by the International Seabed Authority (ISA). It is operated by an independent researcher. For privacy enquiries contact: ${CONTACT_EMAIL}.`,
      ],
    },
    {
      heading: "Information We Collect",
      paragraphs: [
        "We collect a small amount of data as described in the sections below. We do not operate user accounts or registration systems. We do not sell data to third parties.",
      ],
    },
    {
      heading: "Feedback Form",
      paragraphs: [
        "The site provides an optional feedback form. If you use it, we collect:",
        {
          list: [
            "Your message and the category you selected (working well / bug / suggestion) — required.",
            "Your email address — optional, only if you choose to provide it so we can reply.",
            "A one-way hash of your IP address (SHA-256 with a server-side salt, never the raw IP) — stored for spam prevention only.",
            "Your browser's User-Agent string and the page URL at the time of submission.",
          ],
        },
        "Submissions are stored in our own database and delivered to a private Discord channel operated by the site maintainer. Email addresses are used only to respond to your message and are never shared. You may request deletion of your submission at any time by emailing " + CONTACT_EMAIL + ".",
      ],
    },
    {
      heading: "Google Analytics (GA4)",
      paragraphs: [
        "We use Google Analytics to understand how visitors use the site. GA4 may collect device type, browser, approximate geographic region, pages visited, and interaction events. GA4 uses cookies and similar tracking technologies. Data is processed by Google LLC. You can opt out by declining cookies in our consent banner.",
      ],
    },
    {
      heading: "Cookieless Page-View Counter",
      paragraphs: [
        "We operate a privacy-preserving page-view counter that records only the page path and the date — no IP address, no user identifier, and no personal data of any kind. This aggregate counter runs regardless of your cookie consent choice and is stored in our own database. It is used solely for understanding which pages are visited and is exempt from GDPR consent requirements under the 'strictly necessary' and 'statistical purposes with no individual impact' bases.",
      ],
    },
    {
      heading: "Cookies and Local Storage",
      paragraphs: [
        "We use localStorage (not cookies) to store your consent preference so the banner does not appear on every visit. No personal data is stored in localStorage. Third-party cookies may be set by Google Analytics after you grant consent.",
      ],
    },
    {
      heading: "Data Retention",
      paragraphs: [
        "Page-view counts are retained indefinitely in aggregate form (no personal data). Google Analytics data is retained for 14 months per Google's default GA4 setting. Consent preferences stored in localStorage are cleared when you use the Cookie Settings link or clear your browser storage. Feedback submissions are retained until manually deleted; email addresses within them are deleted on request.",
      ],
    },
    {
      heading: "Legal Basis for Processing (GDPR)",
      paragraphs: [
        "If you are in the EEA or UK, we process data based on:",
        {
          list: [
            "Consent (Article 6(1)(a) GDPR) — for analytics and advertising cookies, activated only after you accept; and for any email address you voluntarily provide in the feedback form.",
            "Legitimate interests (Article 6(1)(f) GDPR) — for basic site functionality, security, and processing feedback messages that do not contain an email address.",
            "Statistical purposes (Recital 162 GDPR) — for the cookieless aggregate page-view counter.",
          ],
        },
      ],
    },
    {
      heading: "Your Rights",
      paragraphs: [
        "Under GDPR and CCPA you have the right to access, rectify, erase, restrict, or port your data, and to object to processing or opt out of data sales. Contact us at " + CONTACT_EMAIL + " to exercise these rights. For Google's data, visit myaccount.google.com.",
      ],
    },
    {
      heading: "Children's Privacy",
      paragraphs: [
        "This site is not directed at children under 13. We do not knowingly collect data from children.",
      ],
    },
    {
      heading: "Changes to This Policy",
      paragraphs: [
        "We may update this policy periodically. The date at the top reflects the most recent revision. Continued use of the site after changes constitutes acceptance.",
      ],
    },
    {
      heading: "Contact",
      paragraphs: [`For privacy questions or data requests: ${CONTACT_EMAIL}`],
    },
  ],
};

export const SOURCE_REPO_URL = "https://github.com/ice13ball/something-rare-engine";

export const TERMS_OF_USE: LegalDoc = {
  title: "Terms of Use",
  updated: "March 2026",
  sections: [
    {
      heading: "About the Site",
      paragraphs: [
        `${SITE_NAME} is an informational and educational tool that visualises publicly available data about deep-sea and terrestrial mining, biodiversity, oceanographic monitoring, and environmental risk. It is provided free of charge for research, education, and public interest purposes.`,
      ],
    },
    {
      heading: "Free to Use — Attribution Required",
      paragraphs: [
        `The visualisations, analysis, maps, and content on ${SITE_NAME} may be freely used by anyone — including individuals, journalists, researchers, non-profit organisations, government bodies, intergovernmental organisations, and commercial companies — subject to one condition: you must credit the source.`,
        "When using or reproducing content from this site, attribution must clearly state:",
        {
          list: [
            `Source: ${SITE_NAME} (${SITE_URL})`,
          ],
        },
        "Attribution must be visible to the audience of the work in which the content appears — for example, as a caption, footnote, slide credit, report citation, or inline link. Removing or obscuring the attribution is not permitted.",
      ],
    },
    {
      // AGPL-3.0 §13 requires that people who use this over a network can reach
      // the source; our own §7(b) additional term (LICENSE-ADDITIONAL-TERMS.md)
      // requires the attribution notice below to be reachable from the running
      // program's UI. The footer's "Source" link and this section are together
      // what satisfy both — neither is decorative.
      heading: "Source Code Licence",
      paragraphs: [
        `The software that runs ${SITE_NAME} is free software, published under the GNU Affero General Public License, version 3 or later. You may use, study, modify and redistribute it under that licence's terms, including commercially.`,
        "The complete corresponding source is available at:",
        { list: [SOURCE_REPO_URL] },
        "One additional term applies, permitted under section 7(b) of the licence. Any redistribution, modification or network deployment must preserve this notice, both in the source files that carry it and in the legal notices shown by the running program:",
        {
          // ⛔ A LITERAL, deliberately — not CODE_DOI_URL or DOCS_DOI_URL.
          //
          // This block is not a citation. It is the verbatim notice that
          // §7(b) requires every redistributor to PRESERVE, and it must match
          // `LICENSE-ADDITIONAL-TERMS.md` character for character. Rewriting
          // it to interpolate a constant would make the required text change
          // whenever the constant does, which is the opposite of preserved.
          //
          // ⚠️ The DOI it names is the documentation record, while the notice
          // governs the code. That reads oddly now that a code record exists,
          // but v1.0.0 is already published and archived with this exact
          // wording, so changing it is Michal's call, not a cleanup. Raised
          // 2026-09-15; unchanged on purpose.
          code: [
            "Based on Abyssal Claims — © 2026 Michal Mazurowski",
            "https://something-rare.com",
            "https://doi.org/10.5281/zenodo.19745884",
          ].join("\n"),
        },
        `The names "Abyssal Claims" and "something-rare.com" are not covered by the licence and may not be used to present a derived work as being this project.`,
        "The licence covers the code only. Several upstream datasets carry their own, sometimes non-commercial, terms, which this licence does not alter — see DATA-LICENCES.md in the repository.",
      ],
    },
    {
      heading: "Data Sources and Accuracy",
      paragraphs: [
        "Data is sourced from the ISA, OBIS, ArgoVis, NASA, WRI, UNEP-WCMC, BirdLife, OpenAQ, MarineRegions.org, and other open public databases. While we endeavour to keep data accurate, we make no warranties regarding completeness or fitness for any particular purpose. Do not rely on this site for regulatory, legal, or commercial decisions — always consult primary sources.",
      ],
    },
    {
      heading: "Acceptable Use",
      paragraphs: [
        "You agree not to:",
        {
          list: [
            "Use the site for any unlawful purpose.",
            "Interfere with or disrupt the site's infrastructure.",
            "Access API endpoints in a way that causes undue load.",
            "Present content from this site as your own original work without attribution.",
          ],
        },
      ],
    },
    {
      heading: "Disclaimers",
      paragraphs: [
        "THE SITE IS PROVIDED \"AS IS\" WITHOUT WARRANTY OF ANY KIND. TO THE FULLEST EXTENT PERMITTED BY LAW, WE DISCLAIM ALL WARRANTIES, EXPRESS OR IMPLIED, INCLUDING WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE.",
      ],
    },
    {
      heading: "Limitation of Liability",
      paragraphs: [
        "IN NO EVENT SHALL WE BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES ARISING FROM YOUR USE OF THE SITE.",
      ],
    },
    {
      heading: "Governing Law",
      paragraphs: [
        "These Terms are governed by the laws of Poland, without regard to conflict of law principles.",
      ],
    },
    {
      heading: "Contact",
      paragraphs: [`For enquiries regarding these Terms: ${CONTACT_EMAIL}`],
    },
  ],
};

export const ABOUT: LegalDoc = {
  title: "About Abyssal Claims",
  updated: "April 2026",
  sections: [
    {
      heading: "What It Is",
      paragraphs: [
        "Abyssal Claims is an open-access analytical platform that brings together publicly available scientific and regulatory datasets relevant to deep-sea and terrestrial mining. It combines 50+ data layers from international scientific bodies, intergovernmental organisations, and government registries into a single interactive 3D globe — giving researchers, regulators, industry, journalists, and the public a shared spatial view of where activities, monitoring infrastructure, and ecosystems intersect.",
        "The platform has two modes:",
        {
          list: [
            "Ocean Mode — deep-sea exploration contracts administered by the International Seabed Authority (ISA), overlaid with biodiversity observations, ocean chemistry, seamounts, hydrothermal vents, and real-time monitoring data.",
            "Land Mode — terrestrial mining context: mine footprints, tailings dams, deforestation, fires, and water risk across the globe.",
          ],
        },
      ],
    },
    {
      heading: "Ocean Layers",
      paragraphs: [
        "The ocean view centres on 31 ISA exploration contracts covering approximately 1.3 million km² of the international seabed Area. These are overlaid with:",
        {
          list: [
            "Species observations — 170,000+ deep-sea records from OBIS (depth ≥ 200 m), showing where biodiversity has been documented inside or near contract areas.",
            "Argo floats — real-time ocean sensors recording temperature, salinity, oxygen, and pH; 30-day rolling window.",
            "Hydrothermal vents — 700+ active and inactive vent fields documented in the InterRidge database. Active vents host endemic chemosynthetic communities and are an active area of research in environmental baseline assessment.",
            "Seamounts — underwater mountains that often support distinctive benthic communities. Cobalt-rich ferromanganese crusts can occur on seamount flanks, making them relevant to both biodiversity research and mineral resource assessment.",
            "OceanSITES moorings and ONC observatories — long-term fixed monitoring stations.",
            "Exclusive Economic Zones (EEZs), marine protected areas, and ISA reserved areas for developing States.",
          ],
        },
      ],
    },
    {
      heading: "Land Layers",
      paragraphs: [
        "The land view maps the terrestrial mining industry and its environmental context:",
        {
          list: [
            "Global Mining Footprints — 74,500+ mine polygons (pits, tailings, waste dumps, processing sites) mapped from Sentinel-2 at 10 m resolution (Maus et al. 2022/2023).",
            "Tailings Dams — 1,800+ mine waste storage facilities with risk classification (WAPHA, Hudson-Edwards et al. 2023, plus Global Tailings Portal disclosures).",
            "Tree Cover Loss — annual deforestation at 30 m resolution, umd_tree_cover_loss v1.13 (University of Maryland / WRI).",
            "Active Fires — near-real-time fire detection from VIIRS aboard Suomi-NPP, NOAA-20 and NOAA-21 (NASA LANCE, updated within 3 hours).",
            "Air Quality Stations — real-time PM2.5, SO₂, NO₂, O₃, and CO from government stations worldwide (OpenAQ).",
            "Water Risk — global water stress, depletion, drought, and flood risk at sub-basin level with mining-specific weighting (WRI Aqueduct 4.0).",
            "Surface Water, Global Dams, Forest Carbon Flux, Soil Organic Carbon — deeper environmental context layers.",
          ],
        },
      ],
    },
    {
      heading: "Why a Shared View",
      paragraphs: [
        "Decisions about mining — whether in the deep sea or on land — depend on combining many independent sources of data: contract boundaries, biodiversity records, oceanographic monitoring, deforestation alerts, water risk assessments, and more. Most of this data is publicly available, but it is scattered across dozens of platforms, formats, and APIs, each with its own access patterns.",
        "Abyssal Claims brings these datasets onto a single interactive globe so that researchers, regulators, industry, journalists, and the public can examine the spatial relationships between extractive activity, monitoring infrastructure, and ecological context using the same view. The platform is non-commercial, neutral on policy questions, and designed to surface data rather than draw conclusions for the user.",
      ],
    },
    {
      heading: "Editorial Stance",
      paragraphs: [
        "Abyssal Claims presents data; it does not advocate for or against any particular mining project, regulatory outcome, or policy position. Every layer is sourced from established scientific or regulatory bodies and linked back to its origin.",
        "Where scientific uncertainty exists in a dataset (e.g. data quality flags on Argo profiles, or activity status in vent catalogues), the platform surfaces it directly rather than smoothing it out. Users are free to draw their own analytical conclusions from the data.",
      ],
    },
    {
      heading: "Data Sources",
      paragraphs: [
        "All data is sourced from open public APIs, scientific databases, and international organisations. Key sources include: ISA, OBIS Occurrence Data (DOI: 10.25607/obis.occurrence.b89117cd), ChEssBase (Ramirez-Llodra 2025) via GBIF, ArgoVis, OceanSITES, Ocean Networks Canada (ONC), USGS, NASA LANCE / FIRMS, OpenAQ, NASA COOLR, WRI Global Forest Watch, WRI Aqueduct, JRC Global Surface Water, Global Dam Watch, Hudson-Edwards et al. 2023 (WAPHA tailings, via Dryad), GRID-Arendal, ISRIC SoilGrids, Maus et al. 2022/2023 (Global Mining Footprints via PANGAEA), and Marine Regions (VLIZ).",
        "Spatial overlap indicators in Ocean Mode are derived by intersecting ISA contract geometries with biodiversity occurrences and Argo float proximity (within 200 km). They are mechanical geometric overlaps, not assessments of impact, risk, or compliance.",
      ],
    },
    {
      heading: "Authorship & Citation",
      id: "citation",
      paragraphs: [
        `Abyssal Claims is built and maintained by ${AUTHOR_NAME} (ORCID: ${ORCID} — ${ORCID_URL}).`,
        "There are two archived records on Zenodo and they are not interchangeable. Cite the one that matches what you used; if you are citing the platform as a whole, cite the software record, which declares the documentation record as its companion.",
        {
          list: [
            `The software — the engine that runs this platform, published under ${CODE_LICENCE}: ${CODE_DOI} (${CODE_DOI_URL})`,
            `The methods and data documentation — sources, refresh strategies, derived products and known limitations, ${DOCS_LICENCE}: ${DOCS_DOI} (${DOCS_DOI_URL})`,
          ],
        },
        "Suggested citation (APA) — software:",
        `Mazurowski, M. (2026). ${CODE_TITLE} (${CODE_VERSION}) [Computer software]. Zenodo. ${CODE_DOI_URL}`,
        "Suggested citation (APA) — methods documentation:",
        `Mazurowski, M. (2026). ${DOCS_TITLE} (Version ${DOCS_VERSION}) [Software documentation]. Zenodo. ${DOCS_DOI_URL}`,
        "BibTeX:",
        {
          code: `@software{mazurowski_abyssal_claims_code_2026,
  author       = {Mazurowski, Michal},
  title        = {Abyssal Claims: source code of a FAIR-aligned integration
                  platform for deep-sea and terrestrial mining transparency},
  year         = {2026},
  publisher    = {Zenodo},
  version      = {${CODE_VERSION}},
  doi          = {${CODE_DOI}},
  url          = {${CODE_DOI_URL}}
}

@misc{mazurowski_abyssal_claims_docs_2026,
  author       = {Mazurowski, Michal},
  title        = {Abyssal Claims: A FAIR-aligned integration platform for
                  deep-sea and terrestrial mining transparency},
  year         = {2026},
  publisher    = {Zenodo},
  version      = {${DOCS_VERSION}},
  doi          = {${DOCS_DOI}},
  url          = {${DOCS_DOI_URL}}
}`,
        },
      ],
    },
    {
      heading: "Contact",
      paragraphs: [
        "Built and maintained by an independent developer. For questions, data issues, or collaboration enquiries:",
        CONTACT_EMAIL,
      ],
    },
  ],
};
