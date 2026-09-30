// Runs the app's own Kaori client (src/services/kaoriHttp.ts) and TruthKey rule against a local sidecar.
import { createHash } from 'node:crypto';
import { createKaoriHttp } from '../src/services/kaoriHttp';
import { latLngToCell } from '../src/lib/h3lite';

const BASE = 'http://127.0.0.1:8787';
const client = (who: string) => createKaoriHttp(BASE, async () => 'tok-' + who);
// same rule as liveTruthKey() in src/state/store.ts
const capturedAt = new Date().toISOString();
const key = ['earth', 'flood_water', 'h3', latLngToCell(4.1755, 73.5093, 8), 'surface', capturedAt.slice(0, 13) + ':00Z'].join(':');
console.log('key', key);

// the payload livePayload() builds: Yes -> { water_present: true, extent }, No -> { water_present: false, extent: 'none' }
async function report(who: string, present: boolean, extent: string) {
  const k = client(who);
  const bytes = Buffer.from('phone photo ' + who + ' ' + Math.random());
  const sha = createHash('sha256').update(bytes).digest('hex');
  // RN sends { uri, name, type }; in node a Blob with a filename stands in for it
  const file = new File([bytes], who + '.jpg', { type: 'image/jpeg' });
  const ev = await k.uploadEvidence(file as never, sha);
  const res = await k.compile({
    truth_key: key,
    claim_type_id: 'earth.flood_water.v1',
    observations: [{ claim_type: 'earth.flood_water.v1', reported_at: capturedAt, geo: { lat: 4.1755, lon: 73.5093 }, payload: { water_present: present, extent }, evidence_refs: [ev] }],
  });
  console.log('compile', who, JSON.stringify(res).slice(0, 200));
}

(async () => {
  console.log('truth before', await client('A').getTruth(key));
  await report('X', true, 'street');
  await report('Y', true, 'street');
  await report('Z', true, 'block');
  const ai = await createKaoriHttp(BASE, async () => 'ai-generalist').validate(key, 'RATIFY', 0.9);
  console.log('after AI  ', ai.status, ai.confidence_score);
  const t = await client('V').validate(key, 'RATIFY', 0.9);
  console.log('after vote', JSON.stringify(t));
  console.log('getTruth  ', JSON.stringify(await client('X').getTruth(key)));
})().catch((e) => {
  console.error('FAILED', e);
  process.exit(1);
});
