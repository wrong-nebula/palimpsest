export type MorphologyType = 'terrace' | 'mound_pit' | 'horikiri';
export type CandidateStatus = 'survivor' | 'rejected';
export type TemporalClass = 'Class A' | 'Class B' | 'Class C' | 'Rejected';
export type TriageFilter = 'All' | 'Class A' | 'Class B' | 'Class C' | 'Rejected';
export type UserAnnotation = 'Confirmed' | 'Natural' | 'Modern';

export type AerialLayerKey = 'ort_USA10' | 'ort_old10' | 'gazo1' | 'seamlessphoto';

export type LayerId =
  | 'rrim'
  | 'raking_sun'
  | 'svf'
  | 'lrm'
  | 'flow_violation'
  | 'rho_gnd'
  | 'coverage'
  | 'ort_USA10'
  | 'ort_old10'
  | 'gazo1'
  | 'seamlessphoto';

export interface LayerMeta {
  id: LayerId;
  label: string;
  shortLabel: string;
  shaderIndex: number;
  isAerial: boolean;
  aerialKey?: AerialLayerKey;
}

export const LAYER_OPTIONS: readonly LayerMeta[] = [
  { id: 'rrim', label: 'Chiba RRIM', shortLabel: 'RRIM', shaderIndex: 0, isAerial: false },
  { id: 'raking_sun', label: 'Live Raking-Light Sun', shortLabel: 'Sun', shaderIndex: 1, isAerial: false },
  { id: 'svf', label: 'Zaksek SVF', shortLabel: 'SVF', shaderIndex: 2, isAerial: false },
  { id: 'lrm', label: 'Hesse LRM', shortLabel: 'LRM', shaderIndex: 3, isAerial: false },
  { id: 'flow_violation', label: 'Drainage Violation', shortLabel: 'Flow', shaderIndex: 4, isAerial: false },
  { id: 'rho_gnd', label: 'Ground Confidence (rho_gnd)', shortLabel: 'rho_gnd', shaderIndex: 5, isAerial: false },
  { id: 'coverage', label: 'Survey coverage by density band', shortLabel: 'Coverage', shaderIndex: 10, isAerial: false },
  { id: 'ort_USA10', label: 'GSI 1945 (ort_USA10)', shortLabel: '1945', shaderIndex: 6, isAerial: true, aerialKey: 'ort_USA10' },
  { id: 'ort_old10', label: 'GSI 1965 (ort_old10)', shortLabel: '1965', shaderIndex: 7, isAerial: true, aerialKey: 'ort_old10' },
  { id: 'gazo1', label: 'GSI 1975 (gazo1)', shortLabel: '1975', shaderIndex: 8, isAerial: true, aerialKey: 'gazo1' },
  { id: 'seamlessphoto', label: 'GSI Today (seamlessphoto)', shortLabel: 'Today', shaderIndex: 9, isAerial: true, aerialKey: 'seamlessphoto' },
] as const;

export interface StudyZoneInfo {
  name: string;
  epsg: number;
  bounds_epsg6676: [number, number, number, number];
  bounds_wgs84: [number, number, number, number];
  gsi_layers_available: string[];
  gsi_attribution: string;
}

export interface FunnelMetrics {
  raw_peaks_or_cells: number;
  after_rho_gnd_gate: number;
  after_raw_ground_confirmation?: number;
  after_morphology_filter: number;
  after_bh_fdr: number;
  after_geomorphic_falsifier: number;
  after_osm_historical_diff: number;
  survivors_total: number;
}

export interface GroundSupport {
  x_6676: number;
  y_6676: number;
  center_rho: number;
  mean_16m: number;
  window_cells: number;
  imagery_review?: {field_priority: string; notes: string};
  native_band_cells: number[];
  code: number;
}

export interface FieldSupport {
  bounds: [number, number, number, number];
  dx: number;
  colors: string[];
  labels: string[];
  calibration: Record<string, {detected: number; total: number}> | null;
  candidates: Record<string, GroundSupport>;
}

export interface CandidateRecord {
  candidate_id: string;
  morphology: MorphologyType;
  status: CandidateStatus;
  temporal_class: TemporalClass;
  rejection_reason: string | null;
  x_6676: number;
  y_6676: number;
  lat: number;
  lon: number;
  area_m2: number;
  wall_height_m: number;
  scarp_slope_deg: number;
  local_relief_m: number;
  mean_rho_gnd: number;
  min_rho_gnd: number;
  upslope_area_m2: number;
  drainage_violation: number;
  p_value: number;
  q_value: number;
  confidence_score: number;
  osm_match: string | null;
  historical_notes: string;
  pack_file: string | null;
  textures: Record<AerialLayerKey, string | null>;
}

export interface CandidatesJson {
  schema_version: string;
  generated_utc: string;
  study_zone: StudyZoneInfo;
  funnel: FunnelMetrics;
  fdr_q: number;
  fdr_p_cutoff: number;
  candidates: CandidateRecord[];
  fieldSupport?: FieldSupport;
}

export interface PlmpHeader {
  magic: string;
  version: number;
  nx: number;
  ny: number;
  x0: number;
  y0: number;
  dx: number;
  n_layers: number;
  n_canopy_pts: number;
  z_min: number;
  z_max: number;
}

export interface PlmpPack {
  header: PlmpHeader;
  rawGridBuffer: Float32Array; // 10 * nx * ny floats
  layers: {
    z_gnd: Float32Array;
    chm: Float32Array;
    rho_gnd: Float32Array;
    rrim_r: Float32Array;
    rrim_g: Float32Array;
    rrim_b: Float32Array;
    svf: Float32Array;
    lrm: Float32Array;
    openness_diff: Float32Array;
    flow_violation: Float32Array;
  };
  canopyPts: Float32Array; // n_canopy_pts * 4 (rel_x, rel_y, z_abs, hag)
  maxHag: number;
}

export type AerialBitmapMap = Record<AerialLayerKey, ImageBitmap | null>;

export interface LoadedCandidateData {
  candidate: CandidateRecord;
  pack: PlmpPack;
  textures: AerialBitmapMap;
  ortUsa10Available: boolean;
  coverage: Float32Array;
}

export interface CaliperSample {
  s: number;       // distance along transect (m)
  relX: number;
  relY: number;
  zGnd: number;
  rhoGnd: number;
  lrm: number;
}

export interface CaliperResult {
  p0: { relX: number; relY: number; zGnd: number };
  p1: { relX: number; relY: number; zGnd: number };
  lengthM: number;
  samples: CaliperSample[];
  wallHeightM: number;
  scarpSlopeDeg: number;
  localReliefM: number;
  lrmMinM: number;
  lrmMaxM: number;
  minRhoGnd: number;
  meanRhoGnd: number;
}

export interface RenderParams {
  peel: number;            // 0..1 (1 = 100% dense canopy, 0 = bare earth)
  zExag: number;           // 1.0..4.0
  primaryLayer: LayerId;
  compareLayer: LayerId;
  splitEnabled: boolean;
  splitX: number;          // 0..1 screen fraction
  sunAzimuthDeg: number;   // 0..360 CW from North
  sunElevationDeg: number; // 2..85
  pointSizePx: number;     // canopy splat radius in meters/world-adjusted
  showGridOverlay: boolean;
}
