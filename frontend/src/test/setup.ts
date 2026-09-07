// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import "@testing-library/jest-dom";
// Initializes the real i18next instance with bundled English resources so
// components using useTranslation() render actual copy, not raw keys or a
// throw from an uninitialized i18n singleton.
import "../i18n";
