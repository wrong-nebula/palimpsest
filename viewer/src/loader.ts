import type {
  AerialBitmapMap,
  AerialLayerKey,
  CandidateRecord,
  CandidatesJson,
  FieldSupport,
  LoadedCandidateData,
  PlmpHeader,
  PlmpPack,
} from './types';

const DATA_BASE = './data';
const PLMP_HEADER_BYTES = 64;
const EXPECTED_LAYERS = 10;

function resolveDataUrl(relativePath: string): string {
  const cleaned = relativePath.replace(/^\.?\//, '');
  return `${DATA_BASE}/${cleaned}`;
}

export async function fetchCandidatesJson(): Promise<CandidatesJson> {
  const url = `${DATA_BASE}/candidates.json`;
  const resp = await fetch(url, { cache: 'no-store' });
  if (!resp.ok) {
    throw new Error(`Failed to fetch ${url}: HTTP ${resp.status} ${resp.statusText}`);
  }
  const json = (await resp.json()) as CandidatesJson;
  if (!json || !Array.isArray(json.candidates)) {
    throw new Error('Invalid candidates.json schema: missing candidates array');
  }
  if (json.funnel.after_raw_ground_confirmation !== undefined) {
    const sidecar = await fetch(resolveDataUrl('field_support.json'), {cache: 'no-store'});
    if (!sidecar.ok) throw new Error('Ground-support catalog is missing');
    json.fieldSupport = await sidecar.json() as FieldSupport;
    for (const c of json.candidates) {
      const item = json.fieldSupport.candidates[c.candidate_id];
      if (!item || item.x_6676 !== c.x_6676 || item.y_6676 !== c.y_6676) {
        throw new Error('Ground-support catalog is out of date');
      }
    }
  }
  return json;
}

export function parsePlmpBinary(buffer: ArrayBuffer): PlmpPack {
  if (buffer.byteLength < PLMP_HEADER_BYTES) {
    throw new Error(`PLMP pack too small: ${buffer.byteLength} bytes`);
  }

  const bytes = new Uint8Array(buffer);
  const magic = String.fromCharCode(bytes[0], bytes[1], bytes[2], bytes[3]);
  if (magic !== 'PLMP') {
    throw new Error(`Invalid PLMP magic: "${magic}"`);
  }

  const dv = new DataView(buffer);
  const version = dv.getUint32(4, true);
  if (version !== 1) {
    throw new Error(`Unsupported PLMP version: ${version}`);
  }

  const nx = dv.getUint32(8, true);
  const ny = dv.getUint32(12, true);
  const x0 = dv.getFloat64(16, true);
  const y0 = dv.getFloat64(24, true);
  const dx = dv.getFloat32(32, true);
  const n_layers = dv.getUint32(36, true);
  const n_canopy_pts = dv.getUint32(40, true);
  const z_min = dv.getFloat32(44, true);
  const z_max = dv.getFloat32(48, true);

  if (n_layers !== EXPECTED_LAYERS) {
    throw new Error(`Expected ${EXPECTED_LAYERS} planar layers, got ${n_layers}`);
  }

  const cellCount = nx * ny;
  const gridBytes = n_layers * cellCount * 4;
  const canopyBytes = n_canopy_pts * 4 * 4;
  const expectedTotal = PLMP_HEADER_BYTES + gridBytes + canopyBytes;

  if (buffer.byteLength < expectedTotal) {
    throw new Error(
      `Truncated PLMP pack: got ${buffer.byteLength} bytes, expected >= ${expectedTotal}`
    );
  }

  const header: PlmpHeader = {
    magic,
    version,
    nx,
    ny,
    x0,
    y0,
    dx,
    n_layers,
    n_canopy_pts,
    z_min,
    z_max,
  };

  // Zero-copy Float32 views on little-endian systems (64 and cellCount*4 are 4-byte aligned)
  const rawGridBuffer = new Float32Array(buffer, PLMP_HEADER_BYTES, n_layers * cellCount);
  const sliceLayer = (idx: number): Float32Array =>
    rawGridBuffer.subarray(idx * cellCount, (idx + 1) * cellCount);

  const canopyOffset = PLMP_HEADER_BYTES + gridBytes;
  const canopyPts = new Float32Array(buffer, canopyOffset, n_canopy_pts * 4);

  let maxHag = 1.0;
  for (let i = 3; i < canopyPts.length; i += 4) {
    const h = canopyPts[i];
    if (Number.isFinite(h) && h > maxHag) {
      maxHag = h;
    }
  }

  return {
    header,
    rawGridBuffer,
    layers: {
      z_gnd: sliceLayer(0),
      chm: sliceLayer(1),
      rho_gnd: sliceLayer(2),
      rrim_r: sliceLayer(3),
      rrim_g: sliceLayer(4),
      rrim_b: sliceLayer(5),
      svf: sliceLayer(6),
      lrm: sliceLayer(7),
      openness_diff: sliceLayer(8),
      flow_violation: sliceLayer(9),
    },
    canopyPts,
    maxHag,
  };
}

export async function fetchPlmpPack(packPath: string): Promise<PlmpPack> {
  const url = resolveDataUrl(packPath);
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error(`Failed to fetch pack ${url}: HTTP ${resp.status}`);
  }
  const buffer = await resp.arrayBuffer();
  return parsePlmpBinary(buffer);
}

async function fetchImageBitmapSafe(relativePath: string | null): Promise<ImageBitmap | null> {
  if (!relativePath) {
    return null;
  }
  const url = resolveDataUrl(relativePath);
  try {
    const resp = await fetch(url);
    if (!resp.ok) {
      return null;
    }
    const blob = await resp.blob();
    return await createImageBitmap(blob);
  } catch {
    return null;
  }
}

export async function loadCandidateTextures(
  candidate: CandidateRecord
): Promise<AerialBitmapMap> {
  const keys: AerialLayerKey[] = ['ort_USA10', 'ort_old10', 'gazo1', 'seamlessphoto'];
  const entries = await Promise.all(
    keys.map(async (key) => {
      const path = candidate.textures?.[key] ?? null;
      const bitmap = await fetchImageBitmapSafe(path);
      return [key, bitmap] as const;
    })
  );
  return {
    ort_USA10: entries[0][1],
    ort_old10: entries[1][1],
    gazo1: entries[2][1],
    seamlessphoto: entries[3][1],
  };
}

let basinCoverage: Promise<Uint8Array> | undefined;

async function coverageCutout(pack: PlmpPack, field?: FieldSupport): Promise<Float32Array> {
  const { nx, ny, x0, y0, dx } = pack.header;
  const local = new Float32Array(nx * ny);
  if (!field) return local.fill(-1);
  if (!basinCoverage) {
    basinCoverage = (async () => {
      const response = await fetch(resolveDataUrl('ground_coverage.u8.gz'), {cache: 'no-store'});
      if (!response.ok || !response.body) throw new Error('Ground coverage raster is missing');
      const bytes = new Uint8Array(await response.arrayBuffer());
      // Static hosts may already have decoded a gzip Content-Encoding.
      if (bytes[0] !== 0x1f || bytes[1] !== 0x8b) return bytes;
      const expanded = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
      return new Uint8Array(await new Response(expanded).arrayBuffer());
    })().catch(err => { basinCoverage = undefined; throw err; });
  }
  const all = await basinCoverage;
  const [west, south, east, north] = field.bounds;
  const width = Math.round((east-west)/field.dx);
  const height = Math.round((north-south)/field.dx);
  const col = Math.round((x0-west)/dx), row = Math.round((y0-south)/dx);
  if (all.length !== width*height || dx !== field.dx || col < 0 || row < 0 ||
      col+nx > width || row+ny > height) throw new Error('Coverage and terrain grids do not align');
  for (let y = 0; y < ny; y++) {
    const start = (row+y)*width+col;
    local.set(all.subarray(start,start+nx), y*nx);
  }
  return local;
}

export async function loadCandidateData(
  candidate: CandidateRecord, field?: FieldSupport
): Promise<LoadedCandidateData> {
  if (!candidate.pack_file) {
    throw new Error(`Candidate ${candidate.candidate_id} has no pack_file`);
  }
  const [pack, textures] = await Promise.all([
    fetchPlmpPack(candidate.pack_file),
    loadCandidateTextures(candidate),
  ]);
  const ortUsa10Available = Boolean(candidate.textures?.ort_USA10 && textures.ort_USA10);
  return {
    candidate,
    pack,
    textures,
    ortUsa10Available,
    coverage: await coverageCutout(pack, field),
  };
}
