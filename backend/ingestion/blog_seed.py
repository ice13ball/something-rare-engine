# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

"""
Initial blog article seed data.
Called from seed_blog_if_empty() in domains/blog.py (via schema.py's ensure_schema())
on first startup when blog_articles is empty.
"""

SEED_ARTICLES = [
    {
        "slug": "what-is-deep-sea-mining",
        "title": "The Resource Race Happening 5,000 Metres Below the Ocean Surface",
        "description": "Deep-sea mining targets three ancient mineral deposit types across the abyssal plains, seamounts, and mid-ocean ridges — and the race to extract them is reshaping international law and ocean conservation.",
        "tags": ["deep-sea mining", "explainer", "ISA"],
        "reading_time_min": 5,
        "published_at": "2026-03-01",
        "content_md": """\
Deep-sea mining is the extraction of mineral resources from the seabed at depths exceeding 200 metres. Unlike conventional mining, operations target three distinct deposit types that formed over millions of years across the abyssal plains, seamounts, and mid-ocean ridges of the international seabed.

## The Three Deposit Types

**Polymetallic nodules** are potato-sized concretions scattered across the floors of the Pacific, Indian, and Atlantic Oceans. They grow at a rate of a few millimetres per million years and contain manganese, nickel, copper, and cobalt — metals critical for electric vehicle batteries and renewable energy infrastructure. The Clarion-Clipperton Zone (CCZ) in the eastern Pacific holds the world's highest-density nodule fields.

**Cobalt-rich ferromanganese crusts** form on the slopes and summits of seamounts, encrusting ancient volcanic rock over tens of millions of years. They are exceptionally rich in cobalt, platinum, and rare-earth elements. Seamounts also host some of the ocean's most biodiverse and least-understood ecosystems, with high proportions of endemic species.

**Polymetallic sulphides** precipitate around hydrothermal vents — submarine hot springs where superheated water laden with dissolved metals vents into the cold deep ocean. When this fluid contacts seawater, metals crash out of solution, building chimney-like structures rich in copper, zinc, gold, and silver. These vent fields are among the most biologically extraordinary environments on Earth.

## Who Governs It?

The international seabed — the area beyond national jurisdiction — is governed by the **International Seabed Authority (ISA)**, an intergovernmental body established under the 1982 United Nations Convention on the Law of the Sea (UNCLOS). The ISA issues exploration contracts to state-sponsored entities and private companies, regulates environmental standards, and collects royalties on behalf of humanity (the seabed is legally defined as the "common heritage of mankind").

As of 2026, the ISA has issued over 30 exploration contracts covering approximately 1.5 million km² of the seabed — an area larger than the combined land area of France, Germany, and Spain.

## Why Now?

The urgency around deep-sea mining is driven by the **clean energy transition**. Electric vehicles, wind turbines, and grid-scale batteries require unprecedented quantities of cobalt, nickel, manganese, and copper. Demand projections suggest that terrestrial sources alone cannot supply the volumes needed. Proponents argue that seabed mining offers a geopolitically neutral supply chain less dependent on a handful of onshore producing nations.

Critics, including the Deep Sea Conservation Coalition and many marine biologists, argue that the ecosystems at risk are irreplaceable and functionally critical to ocean health. Sediment plumes from nodule harvesting can travel hundreds of kilometres, smothering filter-feeding organisms. Vent communities — destroyed when the vent is mined — cannot recover on any human timescale.

## Explore the Data

Abyssal Claims maps every active ISA exploration contract alongside hydrothermal vent fields from the InterRidge Vents Database, biodiversity observations from OBIS, and real-time ocean monitoring from the Argo float programme. Use the interactive 3D map to explore spatial conflicts between mining concessions and the ecosystems they threaten.
""",
    },
    {
        "slug": "isa-contracts-explained",
        "title": "Who Controls the Ocean Floor: The Quiet Power of ISA Mining Licences",
        "description": "The International Seabed Authority issues contracts giving corporations exclusive access to sections of the international seabed — here is how that system works, who holds the licences, and what the governance crisis means.",
        "tags": ["ISA", "governance", "contracts"],
        "reading_time_min": 6,
        "published_at": "2026-03-04",
        "content_md": """\
The International Seabed Authority (ISA) is the intergovernmental body that controls who can mine the international seabed — and on what terms. Understanding how ISA contracts work is essential to following the governance debates now unfolding around deep-sea mining.

## What Is the ISA?

The ISA was established in 1994 when the 1982 United Nations Convention on the Law of the Sea (UNCLOS) entered into force. It is headquartered in Kingston, Jamaica, and currently has 168 member states. Its mandate is to organise and control activities in the international seabed "for the benefit of mankind as a whole," with special consideration for developing nations.

The international seabed — everything beyond the 200-nautical-mile exclusive economic zones of coastal states — is legally defined as the "common heritage of mankind." No country owns it. The ISA acts as its custodian.

## Types of Contracts

The ISA issues two categories of contract:

**Exploration contracts** authorise a contractor to survey a defined area, collect samples, and assess the commercial viability of a deposit. They last 15 years with the possibility of extension. Contractors must submit annual reports, follow environmental regulations, and pay annual fees. Exploration does not authorise extraction.

**Exploitation contracts** authorise actual mining. As of 2026, no exploitation contract has been issued. The ISA's Mining Code — the regulatory framework for exploitation — remains under negotiation, delayed by unresolved disputes over environmental thresholds, royalty structures, and liability rules.

## Who Holds Contracts?

Contracts are held by **sponsored entities**: a company or state institution that is sponsored by an ISA member state. The sponsoring state bears legal responsibility for ensuring the contractor complies with ISA regulations — creating a financial liability that has made some governments cautious.

Current contractors include:

- State entities from China, Russia, South Korea, India, France, Germany, Japan, and others
- Private companies sponsored by small island states, including the Cook Islands, Nauru, and Kiribati — which have become notable sponsors partly because of lower sponsorship costs

China holds the largest number of exploration contracts of any single state.

## The Two-Year Rule and Nauru

In 2021, Nauru triggered what became known as the "two-year rule" by formally notifying the ISA of its intention to begin exploitation, compelling the ISA under UNCLOS to finalise the Mining Code within two years regardless of whether negotiations were complete. The deadline passed in July 2023 without a finalised code, creating significant legal uncertainty about whether mining could proceed anyway.

The episode exposed the tension at the heart of ISA governance: small island states with minimal environmental stake hold disproportionate procedural leverage, and the ISA's decision-making structure — requiring consensus among member states with divergent interests — is poorly equipped for the speed at which industry is pushing for commercial extraction.

## Environmental Obligations

Contractors must conduct environmental baseline studies before any extraction begins, establish "preservation reference zones" left unmined for comparison, and submit environmental management plans. The ISA's environmental regulations have been criticised by scientists as underspecified — particularly regarding sediment plume modelling, the geographic scope of impact assessments, and what counts as "serious harm" to the marine environment.

Several states, including Germany, France, Chile, and New Zealand, have called for a moratorium or precautionary pause on exploitation contracts until environmental standards are strengthened.

## Tracking It Yourself

Abyssal Claims provides a map of every active ISA exploration contract, including contractor name, resource type, contract area in km², and spatial overlap with hydrothermal vent fields and biodiversity hotspots. Each concession page includes ISA contract metadata and a direct link to the ISA's public contract register.
""",
    },
    {
        "slug": "hydrothermal-vents-at-risk",
        "title": "The Submarine Ecosystems That Exist Nowhere Else on Earth — and Where Mining Wants to Go",
        "description": "Hydrothermal vent fields host species found nowhere else on the planet. Spatial analysis of ISA contracts reveals exactly how many active vent fields sit inside or adjacent to active mining licences.",
        "tags": ["hydrothermal vents", "biodiversity", "conservation"],
        "reading_time_min": 6,
        "published_at": "2026-03-07",
        "content_md": """\
Hydrothermal vents are among the most extraordinary environments on Earth. First discovered in 1977 near the Galápagos Islands, they are submarine springs where seawater percolates through cracks in the ocean crust, is superheated by magma, and erupts back into the water column laden with dissolved metals and chemicals. What makes them remarkable is not the geology — it is the life.

## Chemosynthetic Ecosystems

Unlike virtually every other ecosystem on Earth, hydrothermal vent communities are not powered by sunlight. They run on **chemosynthesis**: bacteria and archaea oxidise hydrogen sulphide and methane to produce energy, forming the base of a food web that supports tube worms up to two metres long, ghostly shrimp with no functional eyes, dense colonies of mussels and clams, and predatory fish and crabs that exist nowhere else on the planet.

The species at vent fields are often **endemic** — found at that specific location and nowhere else. When a vent is destroyed, those species are gone. There is no recolonisation pathway, no refugium, no genetic reservoir elsewhere. This is extinction in the most final sense.

The InterRidge Global Database of Active Submarine Hydrothermal Vent Fields catalogues 721 vent fields worldwide. Abyssal Claims cross-references every ISA mining concession against this database, revealing where exploration contracts directly overlap with known vent locations.

## Why Vents Are Targeted

Hydrothermal vents build **polymetallic sulphide deposits** — chimneys and mounds of copper, zinc, gold, and silver precipitated from vent fluids over thousands of years. These deposits are found along mid-ocean ridges and back-arc basins and represent a commercially attractive ore source, particularly for copper and precious metals.

The conflict is direct and unavoidable: mining a sulphide deposit means destroying the vent system that created it.

## The Scale of Overlap

Abyssal Claims spatial analysis finds that a significant fraction of ISA exploration contracts for polymetallic sulphides overlap with known active or recently active vent fields. The precise figure varies depending on the buffer distance applied and whether extinct (no longer venting) systems are included, but even conservative analyses show dozens of conflicts between concession boundaries and vent locations documented in peer-reviewed databases.

## What Science Says

The scientific consensus on vent ecosystem recovery is stark: **recovery from physical disturbance takes decades to centuries**, if it occurs at all. A 2020 review in *Annual Review of Marine Science* found that the fauna characteristic of mature vent ecosystems — the large tube worms, dense bivalve beds, and endemic invertebrates — recover extremely slowly even after natural disturbance events like lava flows, and that mining-scale sediment plumes pose additional threats to communities tens to hundreds of kilometres from the extraction site.

The International Union for Conservation of Nature (IUCN) has classified 33 hydrothermal vent species as threatened on its Red List, with deep-sea mining specifically identified as the primary threat driver.

## What Can Be Done?

Researchers have proposed several measures:

**Preservation reference zones** — areas of identical habitat left unmined to allow scientific comparison and potential recolonisation. ISA regulations require these, but their size and placement remain contested.

**Pre-mining surveys** — comprehensive biodiversity assessment before any extraction, identifying endemic species and population densities. Currently required but subject to methodological disputes.

**Mining moratoria** — several states and the Deep Sea Conservation Coalition have called for a halt to exploitation contracts until the science of impact prediction matures. France, Germany, Chile, and the UK have indicated support for a precautionary pause.

## Follow the Conflicts

Abyssal Claims shows the spatial intersection of every ISA concession with the InterRidge vent database. Click any concession on the map to see how many vent fields lie within its boundaries and review the biodiversity observations recorded by OBIS in the surrounding area. The data is updated weekly.
""",
    },
    {
        "slug": "clarion-clipperton-zone",
        "title": "The Geography of the World's Largest Deep-Sea Mining Rush",
        "description": "The Clarion-Clipperton Zone — larger than the contiguous United States — holds the world's densest polymetallic nodule fields and 17 active ISA contracts. This is what that looks like on a map.",
        "tags": ["Clarion-Clipperton Zone", "deep-sea mining", "ISA", "biodiversity"],
        "reading_time_min": 9,
        "published_at": "2026-03-10",
        "content_md": """\
The Clarion-Clipperton Zone (CCZ) is the most intensively targeted area for deep-sea mining on Earth. Stretching approximately 4.5 million km² across the central Pacific Ocean between Hawaii and Mexico — an area larger than the contiguous United States — it holds the world's largest known deposit of polymetallic nodules. Understanding the CCZ is essential for anyone tracking deep-sea mining policy, biodiversity loss, or the geopolitics of the clean energy transition.

## Where Is the Clarion-Clipperton Zone?

The CCZ lies between roughly 7° and 15° North latitude, bounded to the northwest by the Clarion Fracture Zone and to the southeast by the Clipperton Fracture Zone — the geological fault lines that give the region its name. It sits entirely in international waters, placing it under the jurisdiction of the International Seabed Authority (ISA) rather than any single state.

Water depths range from 4,000 to 5,500 metres. At these depths, the seafloor is cold (around 1–2°C), pitch-dark, and subject to pressures exceeding 400 atmospheres. Currents are sluggish, sedimentation rates are extremely slow, and biological processes that would take weeks at the surface can take thousands of years.

## What Makes the CCZ So Valuable?

The nodule fields of the CCZ contain extraordinary concentrations of strategically critical metals:

- **Manganese** — used in steel alloys and battery cathodes
- **Nickel** — essential for lithium-ion battery chemistries (NMC, NCA)
- **Copper** — the backbone of electrification infrastructure
- **Cobalt** — a critical component in high-energy battery cells

The United States Geological Survey estimates that the CCZ alone holds more nickel and cobalt than all known terrestrial reserves combined. Some industry assessments value the nodule resource at several trillion US dollars, though extraction costs, environmental regulations, and technology readiness make commercial viability highly uncertain.

## Who Holds Contracts in the CCZ?

As of 2026, the ISA has issued 17 exploration contracts in the CCZ — more than half of all active seabed exploration contracts globally. Contractors include:

- **The Metals Company (Canada/Nauru, Tonga, Kiribati)** — the most commercially advanced nodule mining project
- **NORI (Nauru Ocean Resources Inc.)** — targeting the NORI-D block in the eastern CCZ
- **State entities** from China, South Korea, Japan, France, Germany, Belgium, and the United Kingdom
- **GSR (Global Sea Mineral Resources)** — backed by Belgian dredging company DEME

Each contract covers an exploration area of up to 75,000 km², divided into two portions (one relinquished after eight years) to prevent monopolisation.

## The Biodiversity Crisis Hidden on the Seafloor

The CCZ is not a mineral deposit floating in empty water. It is a functioning ecosystem — and one of surprising richness, given its remoteness and depth.

Research expeditions, including the ABYSSLINE project and surveys by the Natural History Museum London, have documented **over 5,000 species** in the CCZ, with estimates suggesting more than half are new to science. Key ecological communities include:

**Nodule-associated fauna:** Sponges, xenophyophores (giant single-celled organisms), holothurians (sea cucumbers), brittle stars, and polychaete worms colonise the nodule surfaces. These nodules are the only hard substrate available on the otherwise soft sediment plains — making them habitat, not just resource.

**Sediment infauna:** Foraminifera, nematodes, and other meiofauna are extraordinarily diverse in CCZ sediments. Their populations and recovery rates following disturbance are poorly understood.

**Megafauna:** Fish, crustaceans, and octopuses use the CCZ floor. Populations are sparse but ecologically connected across vast distances.

The IUCN has assessed the CCZ as one of the highest-priority areas for pre-mining biodiversity baseline research, noting that the knowledge gaps are so severe that impacts cannot currently be meaningfully predicted.

## Mining's Impact on CCZ Ecosystems

Nodule mining involves collector vehicles crawling the seafloor and vacuuming up the top 10–15 cm of sediment along with the nodules. This process:

1. **Physically destroys** all nodule-associated fauna in the collection path
2. **Generates a sediment plume** — a cloud of disturbed particles that can travel hundreds of kilometres, smothering filter feeders and reducing light penetration
3. **Creates a discharge plume** — water pumped back to the seafloor after nodule separation on the surface vessel, laden with fine sediment and altered chemistry
4. **Prevents recovery**: Nodules grow at 1–10 mm per million years. The substrate destroyed in a single mining pass will not recover on any human timescale.

The 1989 DISCOL experiment (a deliberate sediment disturbance in the Peru Basin) is still being monitored today. After 26 years, fauna diversity and biomass had not recovered to pre-disturbance levels.

## Areas of Particular Environmental Interest (APEIs)

In recognition of biodiversity risk, the ISA established nine Areas of Particular Environmental Interest in the CCZ — areas set aside from mining contracts to serve as environmental refugia and comparison reference points. Each APEI covers approximately 160,000 km².

However, independent scientific assessments have raised serious concerns:
- APEIs were designed without adequate biodiversity data and may not be representative of CCZ habitat types
- Some APEIs are located in areas with lower nodule density (biasing them away from the most ecologically rich zones)
- Their boundaries cannot be revised without renegotiating existing contracts

The ISA has acknowledged these limitations and committed to a review, but the timeline remains unclear.

## The Moratorium Debate

As of 2026, several member states have called for a precautionary pause or moratorium on CCZ exploitation contracts until environmental standards are strengthened:

- **France, Germany, Chile, New Zealand, Palau, Fiji, and Samoa** have formally supported a moratorium or precautionary pause
- **Pacific Island nations** most directly threatened by climate change — and some of the same nations sponsoring mining contracts — are divided on the issue
- The ISA's Mining Code, which would set the rules for any exploitation, remains unfinished

No exploitation contract has been issued. The CCZ is currently in an exploration-only phase.

## Tracking the CCZ in Real Time

Abyssal Claims maps all 17 CCZ exploration contracts alongside hydrothermal vent fields, OBIS biodiversity data, and APEI boundaries. Filter by contractor, contract date, or resource type to understand which areas are under pressure and how they overlap with documented ecological communities.
""",
    },
    {
        "slug": "polymetallic-nodules-explained",
        "title": "The Potato-Sized Rocks That Could Decide the Clean Energy Transition",
        "description": "Polymetallic nodules took millions of years to form on the abyssal plain. They contain nickel, cobalt, copper, and manganese — the metals at the heart of the clean energy transition — and the race to mine them is just beginning.",
        "tags": ["polymetallic nodules", "deep-sea mining", "battery metals", "critical minerals"],
        "reading_time_min": 10,
        "published_at": "2026-03-13",
        "content_md": """\
Polymetallic nodules are the most commercially targeted resource in deep-sea mining — and understanding them is essential to understanding why the race to mine the ocean floor has accelerated so dramatically in the past decade. These lumpy, potato-sized rocks have been sitting on the seafloor for tens of millions of years. Now they sit at the centre of a multi-trillion-dollar resource race, a governance crisis at the United Nations, and one of the most contested environmental debates of the clean energy transition.

## What Are Polymetallic Nodules?

Polymetallic nodules (also called manganese nodules or ferromanganese nodules) are mineral accretions that form on the deep seafloor, typically at depths of 4,000–6,000 metres. They range from a few millimetres to over 20 centimetres in diameter, though most commercial deposits consist of nodules in the 2–8 cm range.

They form through two processes:

**Hydrogenous precipitation:** Metals dissolved in seawater — principally manganese, iron, cobalt, and nickel — slowly precipitate onto a nucleus over millions of years. The nucleus can be a shark tooth, a fragment of volcanic rock, or even a fragment of an older nodule.

**Diagenetic precipitation:** Metals flux upward from the seafloor sediment through biological and chemical processes, also accreting onto the nodule surface. This process tends to concentrate nickel and copper.

Most commercially interesting nodules involve both processes.

## Why Are They Worth Billions?

The value of polymetallic nodules is a function of both their metal content and the metals they contain.

**Nickel and cobalt are battery metals.** Lithium-ion batteries in electric vehicles, grid storage systems, and consumer electronics rely on nickel-manganese-cobalt (NMC) cathode chemistries. Both nickel and cobalt supply chains are dominated by a small number of countries — Indonesia and the Philippines for nickel, the Democratic Republic of Congo for cobalt — creating supply-chain risks that Western governments and manufacturers are anxious to diversify away from.

**The scale is extraordinary.** The Clarion-Clipperton Zone (CCZ) alone is estimated to contain 21 billion tonnes of nodules. Even at conservative nickel grades, this represents more nickel than all known terrestrial reserves combined. The United States Geological Survey and independent researchers estimate the CCZ nodules contain:

- 340 million tonnes of nickel
- 290 million tonnes of copper
- 44 million tonnes of cobalt
- 7.1 billion tonnes of manganese

At 2024 commodity prices, the contained metal value of CCZ nodules exceeds **$3 trillion** — though this figure is theoretical, not recoverable, given the costs, engineering challenges, and regulatory uncertainty involved in deep-sea mining.

## How Do They Form — and Why Does It Matter?

Nodule growth rates are measured in millimetres per million years. A nodule 5 cm in diameter may be 5–10 million years old. This extraordinarily slow formation rate is central to the environmental debate around mining:

**Nodules are non-renewable on any human timescale.** Unlike terrestrial mineral deposits, which can theoretically regenerate through geological processes on timescales of thousands of years, a harvested nodule field will not recover for millions of years.

**They are habitat, not just rock.** The nodule surface is the only hard substrate in the surrounding soft-sediment abyssal plain. Sponges, xenophyophores (the world's largest single-celled organisms), polychaete worms, brittle stars, and sea cucumbers all colonise nodule surfaces.

## Where Are the Largest Deposits?

Nodule deposits are found across the Pacific, Indian, and Atlantic Oceans, but commercial interest is concentrated in a handful of regions:

**Clarion-Clipperton Zone (Pacific):** The most heavily contracted region. 17 ISA exploration contracts. Estimated 21 billion tonnes of nodules.

**Peru Basin (Pacific):** A major research focus. The DISCOL disturbance experiment in 1989 is still monitored here, providing the longest-running dataset on seafloor recovery from mining-scale disturbance.

**Central Indian Ocean Basin:** Home to ISA contracts held by India and others. Less studied than the CCZ.

## The Environmental Science Debate

Deep-sea mining proponents frequently argue that nodule mining has a lower environmental footprint than equivalent terrestrial mining. Critics argue this comparison is misleading:

- **Terrestrial mining impacts are known and partially managed.** Deep-sea ecosystem responses to industrial disturbance are not yet understood well enough to predict, let alone mitigate.
- **Recovery times are incomparable.** Terrestrial ecosystems disturbed by mining can recover in decades to centuries. Deep-sea abyssal communities disturbed by nodule harvesting are not expected to recover in millions of years.
- **Sediment plume impacts are transboundary.** A plume generated in a contractor's licensed area does not respect contract boundaries.

## Tracking Nodule Mining Concessions

Abyssal Claims maps every active ISA exploration contract — including all nodule contracts — overlaid on hydrothermal vent fields, OBIS biodiversity data, and APEI boundaries.
""",
    },
    {
        "slug": "how-to-use-abyssal-claims-map",
        "title": "How to Read the Environmental Footprint of Deep-Sea Mining Licences",
        "description": "A complete guide to Abyssal Claims — how to navigate the map, interpret each data layer, and use the cross-layer analysis tools for research, journalism, and policy work.",
        "tags": ["guide", "deep-sea mining map", "how-to", "research"],
        "reading_time_min": 8,
        "published_at": "2026-03-16",
        "content_md": """\
Abyssal Claims is an interactive 3D map of the international seabed — designed for researchers, journalists, policymakers, and anyone who wants to understand what is happening on the ocean floor. This guide explains how to use the map effectively, what data layers are available, and how to get the most out of the tool.

## Getting Started

Visit something-rare.com to open the map. No account is required.

On first load, you'll see the Pacific Ocean centred on the Clarion-Clipperton Zone (CCZ), the most heavily contracted region for deep-sea mining. This is intentional: the CCZ is where the highest concentration of active ISA exploration contracts is located and where the environmental stakes are highest.

**Navigation:**
- **Click and drag** to rotate the globe
- **Scroll or pinch** to zoom in and out
- **Click any layer element** (a contract, a vent field, a data point) to open the detail panel

## Data Layers

The map overlays multiple independent datasets. Each layer can be toggled on or off using the layer controls in the sidebar.

### ISA Mining Concessions

The core layer. Every active exploration contract issued by the International Seabed Authority (ISA) is rendered as a polygon on the seafloor. Colours indicate resource type:

- **Blue** — Polymetallic nodules
- **Orange** — Cobalt-rich ferromanganese crusts
- **Red** — Polymetallic sulphides (hydrothermal vent deposits)

Click any contract polygon to see contractor name, contract date, area in km², and resource category.

### Hydrothermal Vent Fields

Sourced from the **InterRidge Vents Database** — the most comprehensive global catalogue of known hydrothermal vent sites.

**Why it matters:** Hydrothermal vents are targeted by polymetallic sulphide mining contracts. The spatial overlap between vent fields and active contracts — visible directly on the map — reveals the scale of potential conflict.

### Biodiversity Observations (OBIS)

The **Ocean Biodiversity Information System (OBIS)** provides species occurrence records from research expeditions and monitoring programmes. This layer helps answer: which contract areas overlap with documented species richness?

**Interpretation note:** OBIS data reflects where expeditions have gone, not where biodiversity is highest. Absence of data does not mean absence of life.

### Argo Float Monitoring

**Argo** is a global array of robotic ocean floats. Each float dives to depth, collects temperature, salinity, and pressure data, then surfaces to transmit via satellite. The Argo layer shows current positions and recent tracks of floats near active contract zones.

### Seamounts

Seamounts are underwater mountains that rise 1,000 metres or more from the seafloor. They support some of the most biodiverse communities in the deep ocean and are targeted by cobalt-crust mining contracts.

## Using the Map for Research

### Measuring Spatial Overlap

One of the most powerful features is the ability to visualise spatial conflicts between resource contracts and ecological data. With multiple layers enabled simultaneously, you can see at a glance where:

- ISA nodule contracts overlap with OBIS biodiversity hotspots
- Sulphide contracts sit directly on known hydrothermal vent fields
- Contract boundaries approach or breach APEI boundaries

## Using the Map for Journalism

**Verifying claims:** When a company or government makes claims about the location or environmental context of a mining contract, the map lets you verify those claims against ISA data independently.

**Finding overlap stories:** The clearest stories often emerge from spatial overlap — a contract that sits directly on a vent field, or a proposed mining area that conflicts with a protected zone.

**Data sourcing:** All data layers are sourced from public, citable databases (ISA, InterRidge, OBIS, Argo). Each data point includes its source.
""",
    },
    {
        "slug": "argo-floats-ocean-monitoring",
        "title": "What 4,000 Drifting Sensors Are Telling Us About Mining-Adjacent Waters",
        "description": "The Argo programme has built the first near-real-time global picture of the ocean interior. Here is what its temperature, salinity, and oxygen profiles reveal about the waters surrounding active deep-sea mining concessions.",
        "tags": ["Argo floats", "ocean monitoring", "deep-sea mining", "oceanography"],
        "reading_time_min": 7,
        "published_at": "2026-03-19",
        "content_md": """\
The Argo programme is one of the most important ocean monitoring systems ever built. Launched in 2000 as a collaboration between more than 30 countries, Argo has deployed over 4,000 autonomous floats that drift through the world's oceans, measuring temperature, salinity, and — in newer models — oxygen, pH, nitrate, and optical properties. The result is the first near-real-time global picture of the ocean interior.

## How Argo Floats Work

An Argo float is a battery-powered cylinder about 1.5 metres long and 20 centimetres in diameter. It has no propulsion. It operates on a 10-day cycle: the float descends to a parking depth of 1,000 metres, drifts with the prevailing current, then descends further to 2,000 metres before slowly rising to the surface while its sensors record a continuous vertical profile. At the surface it transmits data via satellite — and then the cycle repeats.

**Core Sensors (all Argo floats):**
- Temperature (precision ±0.002°C)
- Salinity via conductivity (precision ±0.005 PSU)
- Pressure (depth to ±2.5 dbar)

**BGC-Argo additions (biogeochemical floats):**
- Dissolved oxygen (O₂)
- pH (ocean acidification indicator)
- Nitrate
- Chlorophyll-a (phytoplankton proxy)
- Particulate backscatter (proxy for organic carbon)

## Why Argo Floats Matter for Deep-Sea Mining

Argo floats are the only instrument system with global coverage of the deep ocean interior at the depths where mining operations would occur. This makes them uniquely useful for:

**Baseline monitoring.** Before any mining begins, Argo data establishes what "normal" looks like: the typical temperature, salinity, and oxygen profiles at a given location, and the natural variability across seasons and years.

**Sediment plume detection.** When nodule mining equipment disturbs the seafloor, it generates sediment plumes that can rise hundreds of metres into the water column and travel laterally for hundreds of kilometres. BGC-Argo floats — measuring backscatter as a proxy for suspended particles — can detect anomalously turbid water that may signal a plume.

**Chemical anomaly detection.** Mining activities can release trace metals, dissolved organic material, and hydrogen sulphide from disturbed sediments. Oxygen and pH sensors can detect changes in water chemistry.

**Drift tracking.** Each Argo float drifts at its parking depth, tracing the path of the water mass it sits in. The drift trajectory is an accurate representation of how a passive particle — like a sediment grain or a larva — would be transported by ocean currents at that depth.

## The Data on Abyssal Claims

Abyssal Claims displays the positions and recent profiles of Argo floats operating near ISA mining concessions. Each float shows its last recorded depth profile, any alarm events (anomalous readings beyond the expected range), and its drift path over the preceding 35 days.

The alarm thresholds are depth-adaptive — what counts as an anomalous reading at 200 metres differs from what is anomalous at 2,000 metres. Floats operating inside or near active mining zones with elevated backscatter, reduced oxygen, or pH anomalies are flagged for closer examination.

## Limitations

Argo floats are not purpose-built mining monitors. Their spatial coverage is determined by oceanic circulation, not by where monitoring is needed. In the Clarion-Clipperton Zone — where most ISA mining contracts are concentrated — float density is lower than in heavily trafficked North Atlantic waters.

Despite these limitations, Argo represents the most comprehensive environmental monitoring dataset available for the deep ocean — and it is publicly accessible in near-real-time through the international Argo data centres.
""",
    },
    {
        "slug": "underwater-noise-pollution",
        "title": "The Acoustic Footprint of Deep-Sea Mining: What It Means for Cetaceans",
        "description": "Industrial noise from deep-sea mining would propagate thousands of kilometres through the deep sound channel. Here is what the science says about the impact on cetaceans — and where the regulatory gaps leave them unprotected.",
        "tags": ["noise pollution", "cetaceans", "deep-sea mining", "marine mammals"],
        "reading_time_min": 8,
        "published_at": "2026-03-22",
        "content_md": """\
The ocean is not a quiet place — but it was never as loud as it is today. Shipping, sonar, seismic surveys, and industrial activity have raised ambient noise levels in some ocean basins by 30 decibels or more since the 1960s. For marine mammals that depend on sound to navigate, communicate, find mates, and hunt, this transformation of the acoustic environment is a serious threat. Deep-sea mining would add an entirely new and geographically concentrated source of noise to one of the least-studied parts of the ocean.

## How Sound Travels in the Ocean

Water is an excellent medium for sound. Sound travels roughly five times faster in seawater than in air (approximately 1,500 m/s versus 340 m/s), and it attenuates far less over distance. Low-frequency sounds produced at depth can propagate thousands of kilometres through the deep sound channel — a thermocline-bounded acoustic waveguide between roughly 600 and 1,200 metres depth where sound refracts back toward the centre rather than spreading and losing energy.

## Sources of Mining Noise

A deep-sea polymetallic nodule mining operation involves three distinct noise-generating systems:

**Seafloor collector vehicles** crawl across the abyssal plain at depths of 4,000–6,000 metres, generating continuous low-frequency mechanical noise directly against the seafloor substrate.

**Riser and lift pump systems** transport a slurry of nodules and seawater 4–6 km vertically to the surface support vessel. The pumps generate intense broadband noise at the seafloor, at mid-water depths, and at the surface.

**Surface support vessels** and shuttle tankers are large industrial ships operating continuously for months at a time.

## Impact on Marine Mammals

**Sperm whales** are the most commonly documented cetacean species in deep-water areas that overlap with ISA mining zones. They dive to 2,000 metres or more to hunt squid using high-frequency echolocation clicks. Elevated ambient noise can mask social communication codas, disrupting group cohesion.

**Beaked whales** are among the deepest-diving cetaceans, regularly reaching 1,500–2,000 metres. They are known to be highly sensitive to anthropogenic noise; the U.S. Navy's sonar exercises have been linked to mass strandings of beaked whales.

**Baleen whales** — including fin whales, blue whales, and sei whales — communicate primarily through low-frequency calls that propagate over hundreds to thousands of kilometres. Mining noise in the 10–1,000 Hz range directly overlaps the communication frequencies of these species.

## The Noise Risk Grid on Abyssal Claims

Abyssal Claims integrates underwater noise risk data from the EMODnet European Marine Observation and Data Network alongside cetacean density estimates from OBIS species occurrence records. The Noise Risk Grid shows 1° cells across the North Atlantic and adjacent seas, colour-coded by a composite risk score that combines noise intensity and cetacean vulnerability.

## Regulatory Status

There is no binding international framework specifically regulating anthropogenic noise in the deep international seabed. The ISA's Mining Code includes draft environmental protection regulations, but noise monitoring requirements remain a contested element.

Enable the Noise Risk Grid layer in Abyssal Claims to see where cetacean density intersects with existing noise pressure. Overlay Mining Concessions to see where proposed extraction zones coincide with areas already under acoustic stress.
""",
    },
    {
        "slug": "isa-mining-code-debate",
        "title": "The Unfinished Rules Governing a Multi-Trillion Dollar Ocean Resource Race",
        "description": "The ISA Mining Code has been under negotiation for decades and remains incomplete. The 2021 two-year rule trigger — and what happened next — has made deep-sea governance one of the defining international law battles of the 2020s.",
        "tags": ["ISA", "Mining Code", "governance", "international law", "moratorium"],
        "reading_time_min": 9,
        "published_at": "2026-03-25",
        "content_md": """\
The International Seabed Authority has been negotiating a Mining Code for commercial deep-sea mining since the 1990s. As of 2026, that code remains unfinished — and the governance debates around it have become one of the defining battles in international environmental law.

## What the Mining Code Is

The Mining Code is the package of rules, regulations, and procedures that would govern commercial exploitation of the international seabed. It covers:

- Application procedures for exploitation contracts
- Environmental impact assessment requirements
- Royalty and benefit-sharing arrangements (the "common heritage of mankind" principle)
- Monitoring, reporting, and inspection obligations
- Liability and compensation mechanisms for environmental damage
- Emergency response procedures

Exploration is already regulated — the ISA has issued over 30 exploration contracts since 2001. But exploration permits allow only data collection and small-scale testing, not commercial extraction. The exploitation regulations needed for commercial mining have never been finalised.

## The Two-Year Rule and the Trigger

In 2021, Nauru — a small Pacific island nation with a sponsorship relationship with Canadian company The Metals Company — invoked the "two-year rule" under UNCLOS Article 162. This provision requires the ISA Council to complete work on the rules, regulations, and procedures for exploitation within two years of receiving a formal request from a sponsored contractor.

The deadline passed in June 2023 without a completed code. Under the interpretation favoured by Nauru and The Metals Company, this means exploitation applications must now be considered even in the absence of finalised regulations.

Most ISA member states, along with the majority of marine scientists and environmental organisations, dispute this interpretation. The debate has exposed deep divisions within the ISA membership between states that want to move quickly to enable mining and those — including France, Germany, New Zealand, and Costa Rica — that have called for a moratorium or precautionary pause.

## The Moratorium Campaign

By 2026, more than 25 countries had officially called for a moratorium or precautionary pause on deep-sea mining. The Deep Sea Conservation Coalition, representing over 100 organisations, has documented the scientific consensus position: the environmental impact of commercial-scale deep-sea mining is not adequately understood, and existing data are insufficient to set meaningful environmental limits.

## What a Final Code Would Need to Address

**Sediment plume standards.** At what concentration of suspended sediment does discharge become legally prohibited? The answer requires baseline data that does not yet exist for most proposed mining areas.

**Reference zone requirements.** The ISA framework requires "reference zones" — unfished control areas adjacent to mining sites used to measure environmental change. But the size, location, and monitoring requirements for these zones remain undefined.

**Species protection.** The ISA's environmental management plan for the CCZ identifies nine Areas of Particular Environmental Interest (APEIs) set aside from mining. Critics argue these areas are too small and poorly sited.

**Liability.** If a sediment plume damages fisheries in a neighbouring country's EEZ, who is liable? The current draft regulations contain no clear liability mechanism.

**Independent science.** The ISA's regulatory body includes member states with direct commercial interests in deep-sea mining contracts. There is no independent scientific panel with binding authority over environmental standards.

## The Governance Stakes

The deep-sea mining governance debate is a test case for international environmental law. The outcomes will determine whether international law can adequately govern industrial activity in the global commons.

Abyssal Claims maps every active ISA exploration contract alongside the environmental data that should inform regulation. The Mining Concessions layer shows all contracts by resource type, contractor, and status. The Protected Areas (APEIs) layer shows the current ISA conservation set-asides — enabling direct visual assessment of whether the protected zones are adequately sited relative to the areas under commercial pressure.
""",
    },
    {
        "slug": "biodiversity-hotspots-deep-sea",
        "title": "The Overlap Between Mining Concessions and Deep-Sea Species Found Nowhere Else",
        "description": "OBIS species occurrence records reveal where deep-sea biodiversity concentrates relative to ISA mining boundaries. The data is striking — and the sampling gaps suggest the true picture is far more alarming.",
        "tags": ["biodiversity", "OBIS", "deep-sea mining", "IUCN", "conservation"],
        "reading_time_min": 8,
        "published_at": "2026-03-28",
        "content_md": """\
The term "biodiversity hotspot" is often associated with tropical rainforests or coral reefs. The deep ocean has its own equivalent: areas where OBIS records — drawn from thousands of research cruises, remotely operated vehicle deployments, and sediment core studies — reveal unusually high concentrations of documented species, many found nowhere else on Earth.

## What Deep-Sea Biodiversity Looks Like

The deep sea — defined as water depths below 200 metres — is the largest living space on Earth by volume. It is also among the least sampled. The species richness that has been documented, despite limited sampling effort, is striking: estimates of total deep-sea species count range from 500,000 to over 10 million, most undescribed.

Biodiversity in the deep ocean clusters around:

**Hydrothermal vents** — where chemosynthetic bacteria support entire ecosystems independent of sunlight.

**Cold seeps** — where methane and hydrogen sulphide seeping from seafloor sediments support chemosynthetic communities, with tube worms, ice worms, and rich microbial mats.

**Seamounts** — underwater mountains that concentrate nutrients in upwelling currents and provide hard substrate for suspension feeders. Seamount summits host high proportions of endemic coral, sponge, and fish species.

**Abyssal plains** — the vast flat expanses at 4,000–6,000 metres depth that are the primary target for polymetallic nodule mining. Despite their apparently featureless surface, nodule fields host a remarkable diversity of small invertebrates in densities of thousands per square metre.

## OBIS: The Ocean Biodiversity Information System

The Ocean Biodiversity Information System is the global open-access repository for marine species occurrence data. As of 2026, OBIS holds over 120 million occurrence records for more than 170,000 species.

In the deep-sea context, OBIS records are disproportionately concentrated in a small number of well-studied locations — the result of decades of research cruises and ROV deployments that are expensive and geographically limited. This creates a significant sampling bias: areas with good OBIS coverage are not necessarily the most biodiverse; they are the most studied.

**This means OBIS hotspots underestimate deep-sea biodiversity.** A location with zero OBIS records is not a species desert — it is likely unstudied.

## IUCN Red List Status in the Deep Sea

The International Union for Conservation of Nature's Red List has assessed fewer than 1% of estimated deep-sea species. Among those assessed:

- **Critically Endangered (CR)** deep-sea species include several seamount endemics and vent organisms where the known population consists of a single vent field or seamount summit
- **Endangered (EN)** species include deep-sea corals, some shark species, and several bivalves from vent and seep communities
- **Vulnerable (VU)** includes a broad range of deep-sea fishes and invertebrates where population data are sparse but declining trends are inferred

Abyssal Claims displays OBIS hotspot data colour-coded by IUCN category, allowing users to filter by threat level and see where the highest-risk species are geographically concentrated relative to ISA mining concessions.

## The Sampling Problem and Mining Risk

**Recovery timescales.** The DISCOL experiment, conducted in the Peru Basin in 1989, physically disturbed 10 km² of nodule field and monitored recovery over 26 years. The 2015 reassessment found that sediment community diversity and abundance had not recovered to pre-disturbance levels after more than a quarter century.

**Connectivity.** Many abyssal invertebrates have extremely limited larval dispersal — they reproduce locally and cannot recolonise disturbed areas from distant populations.

**Unknown unknowns.** Because the abyssal plain has been sampled at an infinitesimal fraction of its total area, the number of undescribed species in any given mining zone is genuinely unknown.

## Explore Biodiversity Hotspots

Abyssal Claims maps OBIS hotspot records across the deep ocean, with IUCN category filtering. Enable the Biodiversity Hotspots layer and use the filter panel to highlight Critically Endangered and Endangered species records. Overlay Mining Concessions to see where the highest-risk biodiversity concentrations fall within or adjacent to active exploration contracts.

The At-Risk Claims panel in the Legend tab ranks concessions by their overlap with documented endangered species observations — providing a prioritised view of where the conflict between mining and biodiversity is most acute.
""",
    },
]
