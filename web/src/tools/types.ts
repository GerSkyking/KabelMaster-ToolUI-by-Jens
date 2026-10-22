import type { Backend } from "../sync";

export interface ToolProps {
  backend: Backend;
  datasetId: number;
  columns: string[];
  creator: string;
  /** Spaltenzuordnung aus dem Kabelzug (u. a. beschriftet Ziel 1/2) */
  mapping: Record<string, string | undefined>;
}
