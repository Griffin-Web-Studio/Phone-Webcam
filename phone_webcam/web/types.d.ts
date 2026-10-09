// Shapes shared with phone_webcam/api.py. Keep the two in sync by hand,
// because type checking cannot cross the Python to JS bridge.

export interface CheckItem {
  key: string;
  label: string;
  ok: boolean;
  required: boolean;
  detail: string;
}

export interface Report {
  app_name: string;
  checks: CheckItem[];
  ready: boolean;
  command: string | null;
}

export type WebcamEvent =
  | { type: "state"; state: string }
  | { type: "log"; line: string };

export interface Api {
  get_report(): Promise<Report>;
  get_state(): Promise<string>;
  start(): Promise<void>;
  stop(): Promise<void>;
}

declare global {
  interface Window {
    pywebview: { api: Api };
    onWebcamEvent?: (event: WebcamEvent) => void;
  }
}
