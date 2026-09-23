# Commercial licensing

The code in this repository is licensed under the **GNU AGPL-3.0-or-later** (see
[`LICENSE`](LICENSE) and [`LICENSE-ADDITIONAL-TERMS.md`](LICENSE-ADDITIONAL-TERMS.md)).
That licence permits commercial use, but requires that a modified version offered to users
over a network also offer its complete corresponding source.

If those conditions do not fit your intended use, **a commercial licence is available.**

## When you might need one

- You want to embed this code, or part of it, in a **closed-source product**.
- You want to run a **modified version as a service** without publishing your changes.
- Your organisation has a **policy against AGPL dependencies** and you need different terms.
- You want the code together with **development, integration or support** work.

## What is on offer

| | |
|---|---|
| **Licence exception** | the same codebase under proprietary terms, one-off or annual |
| **OEM / embedding licence** | for redistribution inside your own product |
| **Licence + development retainer** | licence plus ongoing engineering and support |
| **Custom development** | scoped work on a private branch, invoiced from a registered EU sole proprietorship |

Copyright is **not** for sale — this is licensing, not assignment.

## Two things to know up front

1. **Data is not included and is not licensable by me.** Every map layer is fetched at run
   time from its upstream provider under that provider's own licence, and some are
   non-commercial or carry mandatory citation requirements. See
   [`DATA-LICENCES.md`](DATA-LICENCES.md). A commercial licence to this code does not grant
   any right to upstream data.

   One exception, stated plainly because a buyer would otherwise rely on the sentence above:
   `backend/tests/fixtures/` holds ~1.1 MB of **real** upstream excerpts across 14 sources —
   GEOTRACES seawater rows, ONC ADCP profiles, GLODAP and SOCAT NetCDF slices among
   them. They are there so the parsers are tested against the shapes they actually meet, and
   they travel under their own upstream terms like everything else. They are not mine to
   sublicense either. Four further fixture sets (MEMENTO, seabed lithology, MOSAiC sediment,
   Arctic rivers) are withheld from this package because their terms forbid redistribution or
   are silent — see `DATA-LICENCES.md`.

2. **One dependency is GPL-3.0.** `PyCO2SYS`, used in a single lazily-imported function
   (`backend/services/acidification.py`) for the aragonite-saturation reconstruction, is
   licensed GPL-3.0 and is not mine to relicense. Everything else in the dependency tree is
   permissive (MIT / BSD / Apache) or EUPL-1.2. A proprietary licence therefore covers this
   codebase, not a combined work linking PyCO2SYS. In practice the affected feature is
   confined to that one code path and can be isolated behind a process boundary if a
   closed-source deployment needs it — ask, and it can be scoped.

## Contact

**Michal Mazurowski** — solution architect, Gdansk, Poland
Email: **m.mazurowski@ai-wall.com** (subject line prefix: `[LICENSING] abyssal-claims`)
ORCID: [0009-0007-3786-0310](https://orcid.org/0009-0007-3786-0310)

Please include what you intend to build, whether it will be network-facing, and which parts
of the platform you need. That is usually enough to answer in one reply.
