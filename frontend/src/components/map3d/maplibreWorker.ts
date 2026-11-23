// maplibre-gl 6 looks for `maplibre-gl-worker.mjs` next to the chunk that holds
// maplibre-gl. Vite bundles maplibre into `vendor-maplibre-*.js` and never emits that
// sibling file, so every production build fails with "Worker failed to load" and a
// blank map. Emit the worker as an asset and point maplibre at it explicitly.
import { setWorkerUrl } from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";

setWorkerUrl(new URL(workerUrl, window.location.href).href);
