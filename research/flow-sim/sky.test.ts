// The sky report as the phone sends it (the mission's own inputs, liveTruthKey, livePayload and the
// Kaori client), three reporters in Antalya, then the AI vote and a validator, against a local Kaori.
import { createHash } from 'node:crypto';
import { claimText } from '../src/data/claimText';
import { MISSIONS } from '../src/data/proto';
import { createKaoriHttp } from '../src/services/kaoriHttp';
import { livePayload, liveTruthKey } from '../src/services/liveReport';

const BASE = 'http://127.0.0.1:8787';
const client = (who: string) => createKaoriHttp(BASE, async () => 'tok-' + who);
const m = MISSIONS.find((x) => x.id === 'sky')!;
const capturedAt = new Date().toISOString();
// three phones a few dozen metres apart outside the congress venue
const fixes = { X: { lat: 36.8969, lng: 30.7133 }, Y: { lat: 36.8971, lng: 30.7136 }, Z: { lat: 36.8967, lng: 30.713 } };
const keys = Object.values(fixes).map((f) => liveTruthKey(m, f, capturedAt));
console.log('keys', [...new Set(keys)]);
const key = keys[0];

async function report(who: keyof typeof fixes, cover: string, rain: 'Yes' | 'No') {
  const k = client(who);
  const bytes = Buffer.from('sky photo ' + who + ' ' + Math.random());
  const sha = createHash('sha256').update(bytes).digest('hex');
  const file = new File([bytes], who + '.jpg', { type: 'image/jpeg' });
  const ev = await k.uploadEvidence(file as never, sha);
  const f = fixes[who];
  const payload = livePayload(m, { cover }, rain);
  const res = await k.compile({
    truth_key: liveTruthKey(m, f, capturedAt),
    claim_type_id: m.claim,
    observations: [{ claim_type: m.claim, reported_at: capturedAt, geo: { lat: f.lat, lon: f.lng }, payload, evidence_refs: [ev] }],
  });
  console.log('compile', who, JSON.stringify(payload), '->', res.status, res.status === 202 ? `${res.progress.received} of ${res.progress.required}` : res.status === 200 ? res.truth.status : JSON.stringify(res));
}

(async () => {
  await report('X', 'few', 'No');
  await report('Y', 'few', 'No');
  await report('Z', 'scattered', 'No');
  const ai = await createKaoriHttp(BASE, async () => 'ai-generalist').validate(key, 'RATIFY', 0.9);
  console.log('after AI  ', ai.status, ai.confidence_score);
  const t = await client('V').validate(key, 'RATIFY', 0.9);
  console.log('after vote', t.status, t.confidence_score);
  const truth = (await client('X').getTruth(key))!;
  console.log('truth     ', truth.status, JSON.stringify(truth.claim), '|', claimText(m, truth.claim)?.line);
  console.log('reporters ', truth.detail?.observations.map((o) => o.reporter + ' ' + JSON.stringify(o.payload)).join(' · '));
  console.log('signature ', truth.detail?.security?.keyId ?? JSON.stringify(truth.detail?.security).slice(0, 80));
  if (truth.status !== 'VERIFIED_TRUE') process.exit(1);
})().catch((e) => {
  console.error('FAILED', e);
  process.exit(1);
});
