/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Optional absolute backend origin for a split deploy (Vercel frontend → Railway backend). */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
