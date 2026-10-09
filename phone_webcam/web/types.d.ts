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

export interface GateApi {
  get_report(): Promise<Report>;
}

declare global {
  interface Window {
    pywebview: { api: GateApi };
  }
}
