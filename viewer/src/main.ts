import './style.css';
import { OrbitCamera } from './camera';
import { computeCaliperProfile, drawCaliperProfileCanvas, raycastTerrain } from './caliper';
import { buildGpx11Xml, triggerGpxDownload } from './gpx';
import { fetchCandidatesJson, loadCandidateData } from './loader';
import { filterCandidates, getRejected, loadAnnotations, saveAnnotations, type AnnotationMap } from './triage';
import {
  LAYER_OPTIONS,
  type CaliperResult,
  type CandidateRecord,
  type CandidatesJson,
  type LayerId,
  type LoadedCandidateData,
  type RenderParams,
  type TriageFilter,
  type UserAnnotation,
} from './types';
import { TerrainBenchViewport, WebGpuContext } from './webgpu/engine';

const LAYER_LEGENDS: Record<LayerId, string> = {
  rrim: 'Chiba RRIM: Slope (Red) + Differential Openness I_10',
  raking_sun: 'Live Raking-Light Sun: Real-time WGSL shadows + Lambertian relief',
  svf: 'Zaksek SVF: Dark indigo (sheltered pits/ditches) -> Ivory (exposed crests)',
  lrm: 'Hesse LRM: Cobalt (-2m cut/ditch) -> Slate (0m) -> Amber (+2m mound/wall)',
  flow_violation: 'Drainage Violation: Slate (0.0) -> Purple -> Orange -> Yellow (1.0)',
  coverage: 'Local density below 0.5 pts/m² is excluded. Other colors show the 16 m mean.',
  rho_gnd: 'Ground Confidence: RED WARNING < 0.5 pts/m² (TIN hallucination risk)',
  ort_USA10: 'GSI 1945 (ort_USA10) draped on 0.5m bare-earth mesh',
  ort_old10: 'GSI 1965 (ort_old10) draped on 0.5m bare-earth mesh',
  gazo1: 'GSI 1975 (gazo1) draped on 0.5m bare-earth mesh',
  seamlessphoto: 'GSI Today (seamlessphoto) draped on 0.5m bare-earth mesh',
};

function classBadgeClass(tc: CandidateRecord['temporal_class']): string {
  switch (tc) {
    case 'Class A':
      return 'badge badge-a';
    case 'Class B':
      return 'badge badge-b';
    case 'Class C':
      return 'badge badge-c';
    default:
      return 'badge badge-rej';
  }
}

function drawSunGizmo(canvas: HTMLCanvasElement, azDeg: number, elDeg: number): void {
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  const w = canvas.width;
  const h = canvas.height;
  const cx = w * 0.5;
  const cy = h * 0.5;
  const R = Math.min(cx, cy) - 7;

  ctx.clearRect(0, 0, w, h);

  // Outer compass rings (elevation 0°, 30°, 60°)
  ctx.strokeStyle = '#253348';
  ctx.lineWidth = 1;
  for (const frac of [1.0, 0.66, 0.33]) {
    ctx.beginPath();
    ctx.arc(cx, cy, R * frac, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.beginPath();
  ctx.moveTo(cx - R, cy);
  ctx.lineTo(cx + R, cy);
  ctx.moveTo(cx, cy - R);
  ctx.lineTo(cx, cy + R);
  ctx.stroke();

  ctx.fillStyle = '#7c8ea6';
  ctx.font = '9px ui-monospace, monospace';
  ctx.textAlign = 'center';
  ctx.fillText('N', cx, 9);

  // Sun handle position: azDeg CW from North (+up in canvas = -Y)
  const azRad = (azDeg * Math.PI) / 180;
  const rFrac = Math.max(0.05, Math.min(1.0, (90 - elDeg) / 90));
  const sx = cx + Math.sin(azRad) * R * rFrac;
  const sy = cy - Math.cos(azRad) * R * rFrac;

  ctx.strokeStyle = 'rgba(250, 204, 21, 0.55)';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(cx, cy);
  ctx.lineTo(sx, sy);
  ctx.stroke();

  ctx.fillStyle = '#facc15';
  ctx.beginPath();
  ctx.arc(sx, sy, 5, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = '#0b0f16';
  ctx.lineWidth = 1.5;
  ctx.stroke();
}

async function bootstrap(): Promise<void> {
  const statusBanner = document.getElementById('status-banner') as HTMLDivElement;
  const showError = (msg: string) => {
    statusBanner.textContent = msg;
    statusBanner.classList.remove('hidden');
  };

  // DOM Elements
  const primaryCanvas = document.getElementById('gpu-canvas-primary') as HTMLCanvasElement;
  const compareCanvas = document.getElementById('gpu-canvas-compare') as HTMLCanvasElement;
  const comparePane = document.getElementById('compare-pane') as HTMLDivElement;
  const inspector = document.getElementById('inspector') as HTMLElement;

  const studyZoneLabel = document.getElementById('study-zone-label') as HTMLSpanElement;
  const triagePills = document.getElementById('triage-pills') as HTMLDivElement;
  const candidateSelect = document.getElementById('candidate-select') as HTMLSelectElement;
  const rejectedCompareSelect = document.getElementById('select-rejected-compare') as HTMLSelectElement;
  const rejectedPickerRow = document.getElementById('rejected-picker-row') as HTMLDivElement;

  const btnSideBySide = document.getElementById('btn-side-by-side') as HTMLButtonElement;
  const btnCaliper = document.getElementById('btn-caliper') as HTMLButtonElement;
  const chkConfirmedOnly = document.getElementById('chk-confirmed-only') as HTMLInputElement;
  const btnExportGpx = document.getElementById('btn-export-gpx') as HTMLButtonElement;
  const btnToggleInspector = document.getElementById('btn-toggle-inspector') as HTMLButtonElement;

  const sliderPeel = document.getElementById('slider-peel') as HTMLInputElement;
  const valPeel = document.getElementById('val-peel') as HTMLSpanElement;
  const sliderZExag = document.getElementById('slider-zexag') as HTMLInputElement;
  const valZExag = document.getElementById('val-zexag') as HTMLSpanElement;

  const chkSplitWipe = document.getElementById('chk-split-wipe') as HTMLInputElement;
  const selectPrimaryLayer = document.getElementById('select-primary-layer') as HTMLSelectElement;
  const selectCompareLayer = document.getElementById('select-compare-layer') as HTMLSelectElement;
  const sliderSplitX = document.getElementById('slider-split-x') as HTMLInputElement;
  const valSplitX = document.getElementById('val-split-x') as HTMLSpanElement;
  const splitOverlay = document.getElementById('split-overlay') as HTMLDivElement;
  const splitHandle = document.getElementById('split-handle') as HTMLDivElement;
  const splitLabelLeft = document.getElementById('split-label-left') as HTMLDivElement;
  const splitLabelRight = document.getElementById('split-label-right') as HTMLDivElement;
  const layerLegend = document.getElementById('layer-legend') as HTMLDivElement;

  const sunGizmo = document.getElementById('sun-gizmo') as HTMLCanvasElement;
  const sliderSunAz = document.getElementById('slider-sun-az') as HTMLInputElement;
  const sliderSunEl = document.getElementById('slider-sun-el') as HTMLInputElement;
  const valSunAz = document.getElementById('val-sun-az') as HTMLSpanElement;
  const valSunEl = document.getElementById('val-sun-el') as HTMLSpanElement;
  const valSunReadout = document.getElementById('val-sun-readout') as HTMLSpanElement;

  const caliperCanvas = document.getElementById('caliper-canvas') as HTMLCanvasElement;
  const btnClearCaliper = document.getElementById('btn-clear-caliper') as HTMLButtonElement;
  const roWall = document.getElementById('ro-wall') as HTMLElement;
  const roSlope = document.getElementById('ro-slope') as HTMLElement;
  const roLrm = document.getElementById('ro-lrm') as HTMLElement;
  const roRho = document.getElementById('ro-rho') as HTMLElement;
  const roRhoCard = document.getElementById('ro-rho-card') as HTMLDivElement;

  const hudCid = document.getElementById('hud-cid') as HTMLElement;
  const hudClass = document.getElementById('hud-class') as HTMLSpanElement;
  const hudAnnot = document.getElementById('hud-annot') as HTMLSpanElement;
  const hudMeta = document.getElementById('hud-meta') as HTMLDivElement;
  const hudRhoWarn = document.getElementById('hud-rho-warn') as HTMLDivElement;
  const hudRejReason = document.getElementById('hud-rej-reason') as HTMLDivElement;

  const cmpCid = document.getElementById('cmp-cid') as HTMLElement;
  const cmpMeta = document.getElementById('cmp-meta') as HTMLDivElement;
  const cmpRejReason = document.getElementById('cmp-rej-reason') as HTMLDivElement;

  const gsiCredit = document.getElementById('gsi-credit') as HTMLDivElement;
  const usa10Unavailable = document.getElementById('usa10-unavailable') as HTMLDivElement;
  const valQval = document.getElementById('val-qval') as HTMLSpanElement;
  const candNotes = document.getElementById('cand-notes') as HTMLDivElement;
  const annotButtons = Array.from(document.querySelectorAll<HTMLButtonElement>('.btn-annot'));

  // Populate layer selects
  for (const opt of LAYER_OPTIONS) {
    const o1 = document.createElement('option');
    o1.value = opt.id;
    o1.textContent = opt.label;
    selectPrimaryLayer.appendChild(o1);

    const o2 = document.createElement('option');
    o2.value = opt.id;
    o2.textContent = opt.label;
    selectCompareLayer.appendChild(o2);
  }
  selectPrimaryLayer.value = 'rrim';
  selectCompareLayer.value = 'svf';

  let gpu: WebGpuContext;
  try {
    gpu = await WebGpuContext.create();
  } catch (err) {
    showError(`WebGPU initialization failed: ${(err as Error).message}`);
    return;
  }

  let manifest: CandidatesJson;
  try {
    manifest = await fetchCandidatesJson();
  } catch (err) {
    showError(`Data load error: ${(err as Error).message}`);
    return;
  }

  const field = manifest.fieldSupport;
  const coverageLegend = document.getElementById('coverage-legend')!;
  const supportSummary = document.getElementById('support-summary')!;
  const coverageKeys = ['[0.5, 1.0)', '[1.0, 2.5)', '[2.5, 5.0)', '>= 5.0'];
  const recovery = (code: number) => field?.calibration?.[coverageKeys[code-2]];
  if (field) {
    document.getElementById('coverage-map-link')!.classList.remove('hidden');
    const title = document.createElement('strong');
    title.textContent = 'Ground pts/m² · calibration recovery';
    coverageLegend.append(title);
    field.labels.forEach((label, index) => {
      const row = document.createElement('div');
      const chip = document.createElement('i');
      chip.style.backgroundColor = field.colors[index];
      const sample = recovery(index);
      const note = sample ? `${sample.detected}/${sample.total} sites` : (index === 0 ? 'Excluded' : 'Untested');
      const range = index === 0 ? '<0.5 local' : index === 1 ? '<0.5 context' : label;
      row.append(chip, document.createTextNode(`${range} · ${note}`));
      coverageLegend.append(row);
    });
  } else {
    for (const select of [selectPrimaryLayer, selectCompareLayer]) {
      const option = select.querySelector<HTMLOptionElement>('option[value="coverage"]');
      if (option) option.disabled = true;
    }
  }
  studyZoneLabel.textContent = manifest.study_zone?.name || 'Seeing Space · Forest X-Ray';
  if (manifest.study_zone?.gsi_attribution) {
    gsiCredit.textContent = manifest.study_zone.gsi_attribution;
  }

  const primaryViewport = new TerrainBenchViewport(gpu, primaryCanvas);
  const compareViewport = new TerrainBenchViewport(gpu, compareCanvas);
  const camera = new OrbitCamera();

  const renderParams: RenderParams = {
    peel: 1.0,
    zExag: 1.5,
    primaryLayer: 'rrim',
    compareLayer: 'svf',
    splitEnabled: false,
    splitX: 0.5,
    sunAzimuthDeg: 315,
    sunElevationDeg: 18,
    pointSizePx: 0.42,
    showGridOverlay: false,
  };

  let activeFilter: TriageFilter = 'All';
  let annotations: AnnotationMap = loadAnnotations();
  let sideBySide = false;
  let caliperMode = false;
  let primaryData: LoadedCandidateData | null = null;
  let compareData: LoadedCandidateData | null = null;
  let caliperResult: CaliperResult | null = null;
  let caliperP0: { relX: number; relY: number; zGnd: number } | null = null;
  const packCache = new Map<string, LoadedCandidateData>();
  const centerElevations = new Map<string, number>();

  let needsRender = true;
  const requestRender = () => {
    needsRender = true;
  };

  const getDataCached = async (c: CandidateRecord): Promise<LoadedCandidateData> => {
    const existing = packCache.get(c.candidate_id);
    if (existing) return existing;
    const loaded = await loadCandidateData(c, manifest.fieldSupport);
    packCache.set(c.candidate_id, loaded);
    // Record center bare-earth elevation for GPX <ele>
    const { nx, ny, z_min, z_max } = loaded.pack.header;
    const midIdx = Math.floor(ny / 2) * nx + Math.floor(nx / 2);
    const zMid = loaded.pack.layers.z_gnd[midIdx] ?? 0.5 * (z_min + z_max);
    centerElevations.set(c.candidate_id, zMid);
    return loaded;
  };

  // Update triage counts
  const allCandidates = manifest.candidates;
  const setCount = (id: string, n: number) => {
    const el = document.getElementById(id);
    if (el) el.textContent = String(n);
  };
  setCount('cnt-all', allCandidates.length);
  setCount('cnt-a', allCandidates.filter((c) => c.temporal_class === 'Class A').length);
  setCount('cnt-b', allCandidates.filter((c) => c.temporal_class === 'Class B').length);
  setCount('cnt-c', allCandidates.filter((c) => c.temporal_class === 'Class C').length);
  setCount('cnt-rej', allCandidates.filter((c) => c.temporal_class === 'Rejected').length);

  const rejectedList = getRejected(allCandidates);
  for (const r of rejectedList) {
    const opt = document.createElement('option');
    opt.value = r.candidate_id;
    opt.textContent = `${r.candidate_id} · ${r.morphology} (${r.rejection_reason ?? 'rejected'})`;
    rejectedCompareSelect.appendChild(opt);
  }

  const updateGsiAnd1945Banner = () => {
    const hasAnyAerial = Boolean(
      primaryData &&
        (primaryData.textures.ort_USA10 ||
          primaryData.textures.ort_old10 ||
          primaryData.textures.gazo1 ||
          primaryData.textures.seamlessphoto)
    );
    const gsiAvailInZone = (manifest.study_zone?.gsi_layers_available?.length ?? 0) > 0;
    const aerialSelected =
      LAYER_OPTIONS.find((l) => l.id === renderParams.primaryLayer)?.isAerial ||
      (renderParams.splitEnabled &&
        LAYER_OPTIONS.find((l) => l.id === renderParams.compareLayer)?.isAerial);

    gsiCredit.classList.toggle('hidden', !(hasAnyAerial || gsiAvailInZone || aerialSelected));

    const usa10Missing = Boolean(primaryData && !primaryData.ortUsa10Available);
    usa10Unavailable.classList.toggle('hidden', !usa10Missing);
  };

  const updateAnnotationUi = () => {
    const cid = primaryData?.candidate.candidate_id;
    const activeAnnot = cid ? annotations[cid] : undefined;
    for (const btn of annotButtons) {
      btn.classList.toggle('active', btn.dataset.annot === activeAnnot);
    }
    if (activeAnnot) {
      hudAnnot.textContent = activeAnnot;
      hudAnnot.classList.remove('hidden');
    } else {
      hudAnnot.classList.add('hidden');
    }
  };

  const updateCaliperUi = () => {
    drawCaliperProfileCanvas(caliperCanvas, caliperResult);
    primaryViewport.updateCaliperOverlay(caliperResult, renderParams.zExag);

    if (!caliperResult) {
      roWall.textContent = '—';
      roSlope.textContent = '—';
      roLrm.textContent = '—';
      roRho.textContent = '—';
      roRhoCard.classList.remove('warn');
      requestRender();
      return;
    }

    roWall.textContent = `${caliperResult.wallHeightM.toFixed(2)} m`;
    roSlope.textContent = `${caliperResult.scarpSlopeDeg.toFixed(1)}°`;
    roLrm.textContent = `${caliperResult.localReliefM.toFixed(2)} m`;
    roRho.textContent = `${caliperResult.minRhoGnd.toFixed(2)} / ${caliperResult.meanRhoGnd.toFixed(2)}`;
    roRhoCard.classList.toggle('warn', caliperResult.minRhoGnd < 0.5);
    requestRender();
  };

  const updatePrimaryHud = (c: CandidateRecord) => {
    const support = field?.candidates[c.candidate_id];
    supportSummary.replaceChildren();
    if (field && support) {
      const heading = document.createElement('strong');
      heading.textContent = 'Ground support';
      const body = document.createElement('p');
      const pct = (100 * support.native_band_cells[0] / support.window_cells).toFixed(0);
      const rate = recovery(support.code);
      body.textContent = `Centre ${support.center_rho.toFixed(2)} pts/m². The 16 m square averages ${support.mean_16m.toFixed(2)} pts/m², with ${pct}% in blackout. ` +
        (rate ? `This density band recovered ${rate.detected} of ${rate.total} calibration sites.` : 'This position is outside the calibrated search bands.');
      supportSummary.append(heading, body);
      if (support.imagery_review) {
        const note = document.createElement('p');
        note.textContent = (support.imagery_review.field_priority === 'hold' ? 'Field shortlist on hold. ' : 'Aerial review. ') +
          support.imagery_review.notes;
        supportSummary.append(note);
      }
    }
    hudCid.textContent = c.candidate_id;
    hudClass.textContent = c.temporal_class;
    hudClass.className = classBadgeClass(c.temporal_class);
    hudMeta.textContent =
      `${c.morphology} · wall ${c.wall_height_m.toFixed(1)}m · scarp ${c.scarp_slope_deg.toFixed(1)}° · ` +
      `rho ${c.mean_rho_gnd.toFixed(2)}/m² · (${c.lat.toFixed(5)}, ${c.lon.toFixed(5)})`;

    const lowRho = c.min_rho_gnd < 0.5 || c.mean_rho_gnd < 0.5;
    hudRhoWarn.classList.toggle('hidden', !lowRho);

    if (c.rejection_reason) {
      hudRejReason.textContent = `Rejected: ${c.rejection_reason}`;
      hudRejReason.classList.remove('hidden');
    } else {
      hudRejReason.classList.add('hidden');
    }

    valQval.textContent = `q=${c.q_value.toExponential(2)}`;
    candNotes.textContent = c.historical_notes || (c.osm_match ? `OSM: ${c.osm_match}` : 'No historical/OSM notes.');
    updateAnnotationUi();
    updateGsiAnd1945Banner();
  };

  const selectPrimaryCandidate = async (candidateId: string) => {
    const rec = allCandidates.find((c) => c.candidate_id === candidateId);
    if (!rec || !rec.pack_file) return;
    try {
      const data = await getDataCached(rec);
      primaryData = data;
      primaryViewport.uploadCandidateData(data);
      caliperResult = null;
      caliperP0 = null;
      updateCaliperUi();
      updatePrimaryHud(rec);
      statusBanner.classList.add('hidden');
      requestRender();
    } catch (err) {
      showError(`Failed to load ${rec.candidate_id}: ${(err as Error).message}`);
    }
  };

  const selectCompareCandidate = async (candidateId: string) => {
    const rec = allCandidates.find((c) => c.candidate_id === candidateId);
    if (!rec || !rec.pack_file) return;
    try {
      const data = await getDataCached(rec);
      compareData = data;
      compareViewport.uploadCandidateData(data);
      cmpCid.textContent = rec.candidate_id;
      const comparisonSupport = field?.candidates[rec.candidate_id];
      cmpMeta.textContent = `${rec.morphology} · rho ${rec.mean_rho_gnd.toFixed(2)}/m² · flow ${rec.drainage_violation.toFixed(2)}` +
        (comparisonSupport ? ` · 16 m density ${comparisonSupport.mean_16m.toFixed(2)}/m²` : '');
      cmpRejReason.textContent = rec.rejection_reason ? `Reason: ${rec.rejection_reason}` : 'Rejected decoy';
      requestRender();
    } catch (err) {
      showError(`Failed to load decoy ${rec.candidate_id}: ${(err as Error).message}`);
    }
  };

  const rebuildCandidateDropdown = async () => {
    const list = filterCandidates(allCandidates, activeFilter).filter((c) => Boolean(c.pack_file));
    candidateSelect.innerHTML = '';
    for (const c of list) {
      const opt = document.createElement('option');
      opt.value = c.candidate_id;
      const annot = annotations[c.candidate_id];
      const annotTag = annot ? ` [${annot}]` : '';
      opt.textContent = `${c.candidate_id} · ${c.morphology} · ${c.temporal_class}${annotTag}`;
      candidateSelect.appendChild(opt);
    }
    if (list.length > 0) {
      const keepCurrent = primaryData && list.some((c) => c.candidate_id === primaryData!.candidate.candidate_id);
      const targetId = keepCurrent ? primaryData!.candidate.candidate_id : list[0].candidate_id;
      candidateSelect.value = targetId;
      await selectPrimaryCandidate(targetId);
    }
  };

  // Triage pills click
  triagePills.addEventListener('click', (ev) => {
    const btn = (ev.target as HTMLElement).closest<HTMLButtonElement>('.pill');
    if (!btn || !btn.dataset.filter) return;
    activeFilter = btn.dataset.filter as TriageFilter;
    for (const p of triagePills.querySelectorAll('.pill')) {
      p.classList.toggle('active', p === btn);
    }
    void rebuildCandidateDropdown();
  });

  candidateSelect.addEventListener('change', () => {
    void selectPrimaryCandidate(candidateSelect.value);
  });

  rejectedCompareSelect.addEventListener('change', () => {
    void selectCompareCandidate(rejectedCompareSelect.value);
  });

  // Side-by-side comparison toggle
  const viewportArea = document.getElementById('viewport-area') as HTMLElement;
  btnSideBySide.addEventListener('click', () => {
    sideBySide = !sideBySide;
    btnSideBySide.classList.toggle('active', sideBySide);
    comparePane.classList.toggle('hidden', !sideBySide);
    viewportArea.classList.toggle('side-by-side', sideBySide);
    rejectedPickerRow.classList.toggle('hidden', !sideBySide);
    if (sideBySide && !compareData && rejectedList.length > 0) {
      const firstWithPack = rejectedList.find((r) => Boolean(r.pack_file)) ?? rejectedList[0];
      rejectedCompareSelect.value = firstWithPack.candidate_id;
      void selectCompareCandidate(firstWithPack.candidate_id);
    }
    requestRender();
  });

  // Caliper toggle
  const setCaliperMode = (on: boolean) => {
    caliperMode = on;
    btnCaliper.classList.toggle('active', caliperMode);
    primaryCanvas.classList.toggle('caliper-cursor', caliperMode);
  };
  btnCaliper.addEventListener('click', () => setCaliperMode(!caliperMode));
  btnClearCaliper.addEventListener('click', () => {
    caliperResult = null;
    caliperP0 = null;
    updateCaliperUi();
  });

  // Annotations
  for (const btn of annotButtons) {
    btn.addEventListener('click', () => {
      if (!primaryData) return;
      const cid = primaryData.candidate.candidate_id;
      const val = btn.dataset.annot as UserAnnotation;
      if (annotations[cid] === val) {
        delete annotations[cid];
      } else {
        annotations[cid] = val;
      }
      saveAnnotations(annotations);
      updateAnnotationUi();
      // Update option label in select without reloading pack
      const opt = Array.from(candidateSelect.options).find((o) => o.value === cid);
      if (opt) {
        const c = primaryData.candidate;
        const a = annotations[cid];
        opt.textContent = `${c.candidate_id} · ${c.morphology} · ${c.temporal_class}${a ? ` [${a}]` : ''}`;
      }
    });
  }

  // GPX Export
  btnExportGpx.addEventListener('click', () => {
    let exportList = filterCandidates(allCandidates, activeFilter);
    if (chkConfirmedOnly.checked) {
      exportList = exportList.filter((c) => annotations[c.candidate_id] === 'Confirmed');
    }
    const xml = buildGpx11Xml(
      exportList,
      manifest.study_zone?.name || 'PALIMPSEST',
      centerElevations
    );
    triggerGpxDownload(xml, 'palimpsest_filtered.gpx');
  });

  btnToggleInspector.addEventListener('click', () => {
    inspector.classList.toggle('hidden');
    requestRender();
  });

  // Peel the Forest + Z-Exag
  const setPeelPct = (pct: number) => {
    const clamped = Math.max(0, Math.min(100, pct));
    sliderPeel.value = String(clamped);
    valPeel.textContent = `${clamped}%`;
    renderParams.peel = clamped / 100;
    requestRender();
  };
  sliderPeel.addEventListener('input', () => setPeelPct(Number(sliderPeel.value)));
  for (const chip of document.querySelectorAll<HTMLButtonElement>('[data-peel]')) {
    chip.addEventListener('click', () => setPeelPct(Number(chip.dataset.peel ?? 100)));
  }

  sliderZExag.addEventListener('input', () => {
    renderParams.zExag = Number(sliderZExag.value);
    valZExag.textContent = `${renderParams.zExag.toFixed(1)}x`;
    primaryViewport.updateCaliperOverlay(caliperResult, renderParams.zExag);
    requestRender();
  });

  // Layer & Split-Wipe
  const syncLayerUi = () => {
    const primMeta = LAYER_OPTIONS.find((l) => l.id === renderParams.primaryLayer);
    const cmpMetaOpt = LAYER_OPTIONS.find((l) => l.id === renderParams.compareLayer);
    splitLabelLeft.textContent = primMeta?.shortLabel ?? renderParams.primaryLayer;
    splitLabelRight.textContent = cmpMetaOpt?.shortLabel ?? renderParams.compareLayer;
    coverageLegend.classList.toggle('hidden', !field || (renderParams.primaryLayer !== 'coverage' &&
      !(renderParams.splitEnabled && renderParams.compareLayer === 'coverage')));
    layerLegend.textContent = LAYER_LEGENDS[renderParams.primaryLayer];

    splitOverlay.classList.toggle('hidden', !renderParams.splitEnabled);
    splitHandle.style.left = `${(renderParams.splitX * 100).toFixed(2)}%`;
    valSplitX.textContent = `${Math.round(renderParams.splitX * 100)}%`;
    sliderSplitX.value = String(Math.round(renderParams.splitX * 100));
    updateGsiAnd1945Banner();
    requestRender();
  };

  selectPrimaryLayer.addEventListener('change', () => {
    renderParams.primaryLayer = selectPrimaryLayer.value as LayerId;
    syncLayerUi();
  });
  selectCompareLayer.addEventListener('change', () => {
    renderParams.compareLayer = selectCompareLayer.value as LayerId;
    syncLayerUi();
  });
  chkSplitWipe.addEventListener('change', () => {
    renderParams.splitEnabled = chkSplitWipe.checked;
    syncLayerUi();
  });
  sliderSplitX.addEventListener('input', () => {
    renderParams.splitX = Number(sliderSplitX.value) / 100;
    syncLayerUi();
  });

  // Interactive Split Handle drag
  let draggingSplit = false;
  splitHandle.addEventListener('pointerdown', (ev) => {
    ev.stopPropagation();
    draggingSplit = true;
    splitHandle.setPointerCapture(ev.pointerId);
  });
  splitHandle.addEventListener('pointermove', (ev) => {
    if (!draggingSplit) return;
    const rect = primaryCanvas.getBoundingClientRect();
    const nx = (ev.clientX - rect.left) / Math.max(1, rect.width);
    renderParams.splitX = Math.max(0.02, Math.min(0.98, nx));
    syncLayerUi();
  });
  splitHandle.addEventListener('pointerup', () => {
    draggingSplit = false;
  });

  // Sun Azimuth & Elevation Gizmo + Sliders
  const syncSunUi = () => {
    sliderSunAz.value = String(Math.round(renderParams.sunAzimuthDeg));
    sliderSunEl.value = String(Math.round(renderParams.sunElevationDeg));
    valSunAz.textContent = `${Math.round(renderParams.sunAzimuthDeg)}°`;
    valSunEl.textContent = `${Math.round(renderParams.sunElevationDeg)}°`;
    valSunReadout.textContent = `${Math.round(renderParams.sunAzimuthDeg)}° / ${Math.round(renderParams.sunElevationDeg)}°`;
    drawSunGizmo(sunGizmo, renderParams.sunAzimuthDeg, renderParams.sunElevationDeg);
    requestRender();
  };
  sliderSunAz.addEventListener('input', () => {
    renderParams.sunAzimuthDeg = Number(sliderSunAz.value);
    syncSunUi();
  });
  sliderSunEl.addEventListener('input', () => {
    renderParams.sunElevationDeg = Number(sliderSunEl.value);
    syncSunUi();
  });

  let draggingSun = false;
  const updateSunFromPointer = (ev: PointerEvent) => {
    const rect = sunGizmo.getBoundingClientRect();
    const dx = ev.clientX - (rect.left + rect.width * 0.5);
    const dy = ev.clientY - (rect.top + rect.height * 0.5);
    const R = Math.min(rect.width, rect.height) * 0.5 - 7;
    const dist = Math.hypot(dx, dy);
    const az = ((Math.atan2(dx, -dy) * 180) / Math.PI + 360) % 360;
    const rFrac = Math.min(1.0, dist / Math.max(1, R));
    const el = Math.max(2, Math.min(85, 90 - rFrac * 90));
    renderParams.sunAzimuthDeg = az;
    renderParams.sunElevationDeg = el;
    syncSunUi();
  };
  sunGizmo.addEventListener('pointerdown', (ev) => {
    draggingSun = true;
    sunGizmo.setPointerCapture(ev.pointerId);
    updateSunFromPointer(ev);
  });
  sunGizmo.addEventListener('pointermove', (ev) => {
    if (draggingSun) updateSunFromPointer(ev);
  });
  sunGizmo.addEventListener('pointerup', () => {
    draggingSun = false;
  });

  // View presets
  document.getElementById('btn-view-oblique')?.addEventListener('click', () => {
    camera.reset();
    requestRender();
  });
  document.getElementById('btn-view-top')?.addEventListener('click', () => {
    camera.setTopDown();
    requestRender();
  });
  document.getElementById('btn-view-reset')?.addEventListener('click', () => {
    camera.reset();
    requestRender();
  });
  const btnGrid = document.getElementById('btn-toggle-grid') as HTMLButtonElement;
  btnGrid.addEventListener('click', () => {
    renderParams.showGridOverlay = !renderParams.showGridOverlay;
    btnGrid.classList.toggle('active', renderParams.showGridOverlay);
    requestRender();
  });

  // 3D Canvas Pointer Controls (Orbit / Pan / Zoom + Caliper Raycast)
  const attachCanvasControls = (canvas: HTMLCanvasElement, allowCaliper: boolean) => {
    let dragMode: 'none' | 'orbit' | 'pan' | 'caliper' = 'none';
    let lastX = 0;
    let lastY = 0;

    canvas.addEventListener('contextmenu', (ev) => ev.preventDefault());

    canvas.addEventListener('pointerdown', (ev) => {
      canvas.setPointerCapture(ev.pointerId);
      lastX = ev.clientX;
      lastY = ev.clientY;

      if (allowCaliper && (caliperMode || ev.shiftKey) && ev.button === 0 && primaryData) {
        dragMode = 'caliper';
        const rect = canvas.getBoundingClientRect();
        const nx = (ev.clientX - rect.left) / Math.max(1, rect.width);
        const ny = (ev.clientY - rect.top) / Math.max(1, rect.height);
        const ray = camera.screenToRay(nx, ny, rect.width / Math.max(1, rect.height));
        if (ray) {
          const hit = raycastTerrain(primaryData.pack, renderParams.zExag, ray.origin, ray.dir);
          if (hit) {
            caliperP0 = hit;
            caliperResult = computeCaliperProfile(primaryData.pack, hit, hit, 40);
            updateCaliperUi();
          }
        }
        return;
      }

      dragMode = ev.button === 2 || ev.button === 1 || ev.altKey ? 'pan' : 'orbit';
    });

    canvas.addEventListener('pointermove', (ev) => {
      if (dragMode === 'none') return;
      const dx = ev.clientX - lastX;
      const dy = ev.clientY - lastY;
      lastX = ev.clientX;
      lastY = ev.clientY;

      if (dragMode === 'caliper' && primaryData && caliperP0) {
        const rect = canvas.getBoundingClientRect();
        const nx = (ev.clientX - rect.left) / Math.max(1, rect.width);
        const ny = (ev.clientY - rect.top) / Math.max(1, rect.height);
        const ray = camera.screenToRay(nx, ny, rect.width / Math.max(1, rect.height));
        if (ray) {
          const hit = raycastTerrain(primaryData.pack, renderParams.zExag, ray.origin, ray.dir);
          if (hit) {
            caliperResult = computeCaliperProfile(primaryData.pack, caliperP0, hit, 180);
            updateCaliperUi();
          }
        }
        return;
      }

      if (dragMode === 'orbit') {
        camera.orbit(dx, dy);
        requestRender();
      } else if (dragMode === 'pan') {
        camera.pan(dx, dy);
        requestRender();
      }
    });

    canvas.addEventListener('pointerup', () => {
      dragMode = 'none';
    });

    canvas.addEventListener(
      'wheel',
      (ev) => {
        ev.preventDefault();
        camera.zoom(ev.deltaY);
        requestRender();
      },
      { passive: false }
    );
  };

  attachCanvasControls(primaryCanvas, true);
  attachCanvasControls(compareCanvas, false);

  window.addEventListener('resize', () => {
    drawCaliperProfileCanvas(caliperCanvas, caliperResult);
    requestRender();
  });

  // Render loop
  const frame = () => {
    if (needsRender) {
      needsRender = false;
      primaryViewport.render(camera, renderParams);
      if (sideBySide && compareData) {
        compareViewport.render(camera, renderParams);
      }
    }
    requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);

  // Initial sync and load first candidate
  syncLayerUi();
  syncSunUi();
  drawCaliperProfileCanvas(caliperCanvas, null);
  await rebuildCandidateDropdown();

  // Expose lightweight runtime state for automated verification
  (window as unknown as Record<string, unknown>).__PALIMPSEST_VIEWER__ = {
    getState: () => ({
      candidateId: primaryData?.candidate.candidate_id ?? null,
      peel: renderParams.peel,
      primaryLayer: renderParams.primaryLayer,
      compareLayer: renderParams.compareLayer,
      splitEnabled: renderParams.splitEnabled,
      splitX: renderParams.splitX,
      sideBySide,
      caliper: caliperResult,
      ortUsa10Available: primaryData?.ortUsa10Available ?? null,
    }),
  };
}

void bootstrap();
