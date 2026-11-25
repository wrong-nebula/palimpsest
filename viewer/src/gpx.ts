import type { CandidateRecord, TemporalClass } from './types';

function escapeXml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

function symbolForTemporalClass(tc: TemporalClass): string {
  switch (tc) {
    case 'Class A':
      return 'Flag, Red';
    case 'Class B':
      return 'Flag, Blue';
    case 'Class C':
      return 'Flag, Green';
    default:
      return 'Flag, Black';
  }
}

export function buildGpx11Xml(
  candidates: CandidateRecord[],
  studyZoneName: string,
  elevationLookup?: Map<string, number>
): string {
  const nowIso = new Date().toISOString();
  const lines: string[] = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<gpx version="1.1" creator="PALIMPSEST Seeing Space Bench" xmlns="http://www.topografix.com/GPX/1/1">',
    '  <metadata>',
    `    <name>${escapeXml(`PALIMPSEST Filtered Waypoints — ${studyZoneName}`)}</name>`,
    `    <time>${escapeXml(nowIso)}</time>`,
    '  </metadata>',
  ];

  for (const c of candidates) {
    const ele = elevationLookup?.get(c.candidate_id) ?? 0.0;
    const cmt = `[${c.temporal_class}] ${c.morphology} | wall=${c.wall_height_m.toFixed(1)}m scarp=${c.scarp_slope_deg.toFixed(1)}° rho=${c.mean_rho_gnd.toFixed(2)}/m2`;
    const sym = symbolForTemporalClass(c.temporal_class);

    lines.push(`  <wpt lat="${c.lat.toFixed(7)}" lon="${c.lon.toFixed(7)}">`);
    lines.push(`    <ele>${ele.toFixed(2)}</ele>`);
    lines.push(`    <name>${escapeXml(c.candidate_id)}</name>`);
    lines.push(`    <cmt>${escapeXml(cmt)}</cmt>`);
    lines.push(`    <sym>${escapeXml(sym)}</sym>`);
    lines.push(`    <type>${escapeXml(c.temporal_class)}</type>`);
    lines.push('  </wpt>');
  }

  lines.push('</gpx>');
  return lines.join('\n') + '\n';
}

export function triggerGpxDownload(xml: string, filename = 'palimpsest_filtered.gpx'): void {
  const blob = new Blob([xml], { type: 'application/gpx+xml;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
