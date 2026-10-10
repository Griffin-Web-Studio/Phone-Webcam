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

export interface Orientation {
  rotation: number;
  mirror: boolean;
}

export interface StreamSettings {
  resolution: "720p" | "1080p";
  fps: number;
  bitrate: number;
  preview_fps: number;
}

export interface CoverSettings {
  title: string;
  subtitle: string;
  svg: string;
  notices: boolean;
  mirror: boolean;
}

export type ChooseResult =
  | { ok: true; message: string; cover: CoverSettings }
  | { ok: false; message: string };

export type PhoneState =
  | "ready"
  | "unauthorised"
  | "offline"
  | "missing"
  | "unavailable";

export interface CameraInfo {
  id: string;
  label: string;
  facing: string;
}

export interface PreviewEvent {
  type: "preview";
  state: "starting" | "open" | "stopping" | "closed";
  url: string | null;
}

export type WebcamEvent =
  | { type: "state"; state: string }
  | { type: "log"; line: string; debug?: boolean }
  | { type: "debug"; on: boolean }
  | ({ type: "orientation" } & Orientation)
  | PreviewEvent
  | { type: "camera"; id: string }
  | ({ type: "settings" } & StreamSettings)
  | { type: "shutter"; on: boolean }
  | ({ type: "cover" } & CoverSettings)
  | { type: "phone"; state: PhoneState; serial: string }
  | { type: "confirm"; message: string };

export interface Api {
  get_report(): Promise<Report>;
  enter_app(): Promise<void>;
  get_shutter(): Promise<boolean>;
  set_shutter(on: boolean): Promise<void>;
  get_cover(): Promise<CoverSettings>;
  set_cover(cover: Partial<CoverSettings>): Promise<CoverSettings>;
  choose_cover_svg(): Promise<ChooseResult>;
  get_side_width(): Promise<number>;
  set_side_width(width: number): Promise<void>;
  get_state(): Promise<string>;
  get_phone(): Promise<PhoneState>;
  copy_text(text: string): Promise<void>;
  get_debug(): Promise<boolean>;
  set_debug(on: boolean): Promise<void>;
  start(): Promise<void>;
  stop(): Promise<void>;
  list_cameras(): Promise<CameraInfo[]>;
  get_camera(): Promise<string>;
  set_camera(id: string): Promise<void>;
  get_settings(): Promise<StreamSettings>;
  set_settings(settings: Partial<StreamSettings>): Promise<StreamSettings>;
  get_orientation(): Promise<Orientation>;
  set_orientation(rotation: number, mirror: boolean): Promise<void>;
  answer(yes: boolean): Promise<void>;
  show_preview(wanted: boolean): Promise<void>;
}

declare global {
  interface Window {
    pywebview: { api: Api };
    onWebcamEvent?: (event: WebcamEvent) => void;
  }
}
