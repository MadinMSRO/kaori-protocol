import { createKaoriHttp } from '../src/services/kaoriHttp';
import { claimText } from '../src/data/claimText';
import { MISSIONS } from '../src/data/proto';
(async () => {
  const t = await createKaoriHttp('http://127.0.0.1:8787', async () => 'tok-X').getTruth('earth:flood_water:h3:886142a8e7fffff:surface:2026-09-27T13:00Z');
  const m = MISSIONS.find((x) => x.id === 'flood')!;
  console.log(JSON.stringify({ status: t!.status, claim: claimText(m, t!.claim), basis: t!.detail!.basis, obs: t!.detail!.observations.map((o) => [o.reporter, claimText(m, o.payload)!.line, o.evidenceSha256[0].slice(0, 8)]), votes: t!.detail!.votes, sec: t!.detail!.security }, null, 1));
  console.log(claimText(m, { water_present: false, extent: 'none' }));
})();
