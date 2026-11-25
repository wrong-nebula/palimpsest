import type { CandidateRecord, TriageFilter, UserAnnotation } from './types';

const STORAGE_KEY = 'palimpsest.annotations.v1';

export type AnnotationMap = Record<string, UserAnnotation>;

export function loadAnnotations(): AnnotationMap {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    const clean: AnnotationMap = {};
    for (const [k, v] of Object.entries(parsed)) {
      if (v === 'Confirmed' || v === 'Natural' || v === 'Modern') {
        clean[k] = v;
      }
    }
    return clean;
  } catch {
    return {};
  }
}

export function saveAnnotations(map: AnnotationMap): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(map));
  } catch {
    // Ignore storage quota errors in restricted contexts
  }
}

export function filterCandidates(
  candidates: CandidateRecord[],
  filter: TriageFilter
): CandidateRecord[] {
  if (filter === 'All') return candidates;
  return candidates.filter((c) => c.temporal_class === filter);
}

export function getSurvivors(candidates: CandidateRecord[]): CandidateRecord[] {
  return candidates.filter((c) => c.status === 'survivor');
}

export function getRejected(candidates: CandidateRecord[]): CandidateRecord[] {
  return candidates.filter((c) => c.status === 'rejected');
}
