// Types for ssrRoutes.mjs (plain JS so scripts/record-ssr-upstream.mjs can import it under node).
export type SsrRoute = { path: string; kind: 'document' | 'fragment' | 'embed' };
export declare const FIXTURE_PATH: string;
export declare const FORCE_OUTAGE: string;
export declare const SSR_ROUTES: SsrRoute[];
export declare const USER_AGENTS: Record<'human' | 'bot', string>;
