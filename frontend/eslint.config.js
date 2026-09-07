// Flat config (ESLint 9). Deliberately NON-BLOCKING in CI for now: this is the first
// lint pass over ~39.7k lines that were never linted, so the run exists to measure the
// backlog, not to gate on it. Promote rules from "warn" to "error" as they reach zero.
import js from "@eslint/js";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";

export default tseslint.config(
  {
    ignores: [
      "dist/**",
      "node_modules/**",
      "public/**",
      "**/*.snap",
      "coverage/**",
    ],
  },

  // --- Browser/React sources -------------------------------------------------
  {
    files: ["src/**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: { ...globals.browser },
    },
    plugins: { "react-hooks": reactHooks },
    rules: {
      // react-hooks/exhaustive-deps is the single highest-value rule for this
      // codebase: Map3D.tsx alone holds 66 useEffect and 39 useMemo over component
      // state, and a missing dependency there is a stale-closure bug that renders
      // perfectly and shows the wrong data.
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",

      // tsc already enforces noUnusedLocals/noUnusedParameters, so this rule would
      // only duplicate it and double-report the same line.
      "@typescript-eslint/no-unused-vars": "off",

      // Reported, not enforced, until the backlog is known.
      "@typescript-eslint/no-explicit-any": "warn",
      "@typescript-eslint/no-empty-object-type": "warn",
      "no-empty": ["warn", { allowEmptyCatch: true }],
    },
  },

  // --- Node: Express BFF, SSR renderer, checkers ------------------------------
  {
    files: ["*.js", "seo/**/*.js", "scripts/**/*.mjs", "*.config.{js,ts}"],
    extends: [js.configs.recommended],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: { ...globals.node },
    },
    rules: { "no-empty": ["warn", { allowEmptyCatch: true }] },
  },

  // --- Tests ------------------------------------------------------------------
  {
    files: ["src/**/*.test.{ts,tsx}", "src/__tests__/**/*.{ts,tsx}"],
    languageOptions: { globals: { ...globals.node } },
    rules: { "@typescript-eslint/no-explicit-any": "off" },
  },
);
