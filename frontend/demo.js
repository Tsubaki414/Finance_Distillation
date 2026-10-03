/* Read-only demo. Renders the /api/demo-workbench view model; never fabricates a value. */
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const num = n => typeof n === 'number' ? n.toLocaleString('en-US') : esc(n);
let M = null, step = 'facts', persona = 'macro';

const WS = [
  ['event_fact', 'evt', 'Event & Fact'],
  ['kol_persona', 'kol', 'KOL & Persona'],
  ['evergreen', 'evg', 'Evergreen'],
];

function deskCard(key, cls) {
  const d = M.desk[key];
  const rows = {
    event_fact: [['Event replays', 1], ['Typed facts', d.typed_facts], ['Source blocks', d.source_blocks]],
    kol_persona: [['Donors with samples', d.donors_with_samples],
                  ['Point-in-time profiles', d.donors_with_pit_profile],
                  ['Usable at event cutoff', d.donors_usable_at_cutoff],
                  ['Features suppressed', `${d.features_suppressed}/${d.features_compared}`]],
    evergreen: [['Substantive files', d.files], ['Markdown chars', num(d.markdown_chars)],
                ['Person docs', d.raw_documents], ['Independent sources', d.independent_sources]],
  }[key];
  return `<article class="ws" style="--c:var(--${cls});--cbg:var(--${cls}-bg)">
    <h3>${esc(d.label)}</h3>
    <span class="st">${esc(d.status.replace(/_/g, ' '))}</span>
    <dl>${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${num(v)}</dd>`).join('')}</dl>
    <p class="note">${esc(d.note)}</p>
    <div class="src">${esc(d.source_artifact)}</div></article>`;
}

function flowDetail() {
  const s = M.flow.find(x => x.id === step);
  const ex = s.exemplars?.length ? `<div class="block"><h4>Retrieved exemplars (real post IDs)</h4>
      <table><tr><th>post_id</th><th>donor</th><th>cosine</th></tr>
      ${s.exemplars.map(e => `<tr><td>${esc(e.post_id)}</td><td>${esc(e.donor)}</td><td>${e.score}</td></tr>`).join('')}
      </table></div>` : '';
  return `<h3>${s.n}. ${esc(s.title)} <span style="color:var(--ink3);font-weight:400">${esc(s.zh)}</span></h3>
    <span class="badge b-${s.state}">${esc(s.state.replace(/_/g, ' '))}</span>
    <div class="block"><h4>Real inputs we have</h4><ul>${s.have.filter(Boolean).map(h => `<li>${esc(h)}</li>`).join('')}</ul></div>
    <div class="block gap"><h4>Current gap</h4><ul>${s.gap.map(g => `<li>${esc(g)}</li>`).join('')}</ul></div>
    ${ex}
    <div class="block"><h4>Next system action</h4><div class="next">${esc(s.next)}</div></div>
    <div class="src">provenance: ${esc(s.provenance)}</div>`;
}

function personaPanel() {
  const p = M.personas.find(x => x.id === persona);
  return `<div class="tabs">${M.personas.map(x =>
      `<button class="tab" role="tab" aria-selected="${x.id === persona}" data-persona="${x.id}">${esc(x.zh)}</button>`).join('')}</div>
    <div class="panel"><h3 style="margin:0 0 3px;font:600 17px/1.3 Georgia,serif">${esc(p.zh)}</h3>
      <p class="mono" style="margin:0 0 9px">${esc(p.en)}</p>
      <p style="font-size:13.5px;margin:0 0 4px"><strong>Independent question:</strong> ${esc(p.question || '—')}</p>
      <p style="font-size:12.5px;color:var(--ink3);margin:0">Planned donors (retrieval + editorial formula, not learned):
        ${p.planned_donors.map(d => `<code>${esc(d)}</code>`).join(' · ') || '—'}</p>
      <div class="roles">${p.roles.map(r => `<div class="role"><div class="rn">${esc(r.role)}</div>
        <div class="ra">${esc(r.assigned)}</div></div>`).join('')}</div>
      <div class="gate" style="margin-top:12px">${esc(p.warning)}</div>
      <div class="src">${esc(p.source_artifact)}</div></div>`;
}

function evidencePanel() {
  const e = M.evidence, a = e.automated_qa;
  return `<div class="lesson"><strong>为什么这篇被 block：</strong>${esc(e.lesson)}</div>
    <div class="two" style="margin-bottom:13px">
      <div class="panel"><h4 style="margin:0 0 7px;font:600 11px/1 ui-monospace,monospace;letter-spacing:.1em;text-transform:uppercase;color:var(--ink3)">Automated QA said</h4>
        <dl class="kv"><dt>citation integrity</dt><dd>${a.citation_reference_integrity} <span class="pill">passed</span></dd>
        <dt>schema errors</dt><dd>${a.errors} <span class="pill">passed</span></dd>
        <dt>AI phrase flags</dt><dd>${a.ai_surface_patterns} <span class="pill">passed</span></dd>
        <dt>fact coverage</dt><dd>${(a.fact_id_coverage * 100).toFixed(1)}%</dd></dl></div>
      <div class="panel"><h4 style="margin:0 0 7px;font:600 11px/1 ui-monospace,monospace;letter-spacing:.1em;text-transform:uppercase;color:var(--ink3)">Case status</h4>
        <dl class="kv"><dt>run_status</dt><dd>${esc(e.run_status)}</dd>
        <dt>qa_status</dt><dd style="color:var(--stop);font-weight:600">${esc(e.qa_status)}</dd>
        <dt>content_status</dt><dd style="color:var(--stop);font-weight:600">${esc(e.content_status)}</dd>
        <dt>classification</dt><dd>${esc(e.classification)}</dd></dl></div></div>
    ${e.findings.map(f => `<details><summary>${esc(f.id)} · ${esc(f.type.replace(/_/g, ' '))}
        <span class="sev">${esc(f.severity)}</span></summary>
      <div class="body"><dl class="kv">
        ${f.sentence_id ? `<dt>sentence</dt><dd>${esc(f.sentence_id)}</dd>` : ''}
        ${f.fact_id ? `<dt>fact</dt><dd><code>${esc(f.fact_id)}</code> = ${num(f.fact_value)} ${esc(f.fact_unit || '')}</dd>` : ''}
        ${f.expected_display ? `<dt>should read</dt><dd><strong>${esc(f.expected_display)}</strong></dd>` : ''}
        ${f.draft_display ? `<dt>draft wrote</dt><dd style="color:var(--stop)"><strong>${esc(f.draft_display)}</strong></dd>` : ''}
        ${f.claim ? `<dt>claim</dt><dd>${esc(f.claim)}</dd>` : ''}
        ${f.cited_fact_id ? `<dt>cited</dt><dd><code>${esc(f.cited_fact_id)}</code> = ${esc(f.cited_value)} (level)</dd>` : ''}
        ${f.correct_fact_id ? `<dt>should cite</dt><dd><code>${esc(f.correct_fact_id)}</code> = ${esc(f.correct_value)} (change)</dd>` : ''}
        ${f.missing_fact_ids ? `<dt>missing facts</dt><dd>${f.missing_fact_ids.map(x => `<code>${esc(x)}</code>`).join(' ')}</dd>` : ''}
        </dl><p style="margin:6px 0 0;font-size:13px">${esc(f.note)}</p>
        <div class="gate">修复后由此闸门拦截：<strong>${esc(f.gate_that_will_catch_it)}</strong></div></div></details>`).join('')}
    <div class="src">${esc(e.source_artifact)}</div>`;
}

function evergreenPanel() {
  const g = M.evergreen, m = g.manifest, p = g.pools, d = g.dedup;
  const pools = [['production_candidate', 'Production Candidate', 'span review required'],
                 ['knowledge', 'Knowledge', 'no direct quote / no language donor'],
                 ['challenge', 'Challenge', 'held out to test the gates']];
  return `<div class="two">
    <div class="panel"><h4 style="margin:0 0 8px;font:600 11px/1 ui-monospace,monospace;letter-spacing:.1em;text-transform:uppercase;color:var(--ink3)">Corpus composition</h4>
      <dl class="kv"><dt>substantive files</dt><dd>${num(m.files)}</dd>
      <dt>markdown chars</dt><dd>${num(m.markdown_chars)}</dd>
      <dt>with source URL</dt><dd style="color:var(--stop)">${m.with_source_url} / 143</dd>
      <dt>secondary compilations</dt><dd>${m.secondary}</dd>
      <dt>conversion</dt><dd class="mono">${Object.entries(m.conversion_methods).filter(([k]) => k !== 'null').map(([k, v]) => `${esc(k)} ${v}`).join(' · ')}</dd></dl>
      <div class="gate">OCR subsystem: <strong>${esc(p.ocr?.status || 'unknown')}</strong> — ${esc(p.ocr?.consequence || '')}</div>
      <div class="src">${esc(m.source_artifact)}</div></div>
    <div class="panel"><h4 style="margin:0 0 8px;font:600 11px/1 ui-monospace,monospace;letter-spacing:.1em;text-transform:uppercase;color:var(--ink3)">Three pools · person line</h4>
      <table><tr><th>pool</th><th>files</th><th>chars</th><th>rights</th></tr>
      ${pools.map(([k, label, right]) => `<tr><td><strong>${esc(label)}</strong></td>
        <td>${p.counts[k] ?? 0}</td><td>${num(p.chars[k] ?? 0)}</td>
        <td style="font-size:11px;color:var(--ink3)">${esc(right)}</td></tr>`).join('')}</table>
      <div class="src">${esc(p.source_artifact)}</div></div></div>
    <div class="panel" style="margin-top:13px"><h4 style="margin:0 0 8px;font:600 11px/1 ui-monospace,monospace;letter-spacing:.1em;text-transform:uppercase;color:var(--ink3)">Semantic dedup ran before extraction</h4>
      <dl class="kv"><dt>person documents</dt><dd>${d.documents}</dd>
      <dt>independent sources</dt><dd><strong>${d.independent_sources}</strong></dd>
      <dt>chunks</dt><dd>${num(d.chunks)}</dd>
      <dt>with cross-doc near-dup</dt><dd>${num(d.dup_chunks)} (${(d.dup_chunks / d.chunks * 100).toFixed(0)}%)</dd>
      <dt>redundant chars</dt><dd>${num(d.redundant_chars)}</dd></dl>
      <table><tr><th>cluster</th><th>files</th><th>canonical</th><th>redundant</th></tr>
      ${d.clusters.map(c => `<tr><td class="mono">${esc(c.duplicate_cluster_id)}</td><td>${c.member_count}</td>
        <td>${esc(c.canonical_path.split('/').pop())}</td><td>${num(c.chars_redundant)}</td></tr>`).join('')}</table>
      <div class="src">${esc(d.source_artifact)}</div></div>
    <div class="block"><h4>Next</h4><ul>${g.next.map(n => `<li>${esc(n)}</li>`).join('')}</ul></div>`;
}

function render() {
  document.getElementById('gate').textContent =
    `output gate: ${M.output_gate.findings} findings`;
  document.getElementById('app').innerHTML = `
    <section><h2>Workstreams</h2><div class="grid3">${WS.map(([k, c]) => deskCard(k, c)).join('')}</div></section>
    <section><h2>Delivery scoreboard</h2><div class="score">${M.scoreboard.map(s =>
      `<div class="sc ${esc(s.tone)}"><div class="v ${typeof s.value === 'string' ? 'small' : ''}">${num(s.value)}</div>
       <div class="l">${esc(s.label)}</div><div class="d">${esc(s.detail)}</div>
       <div class="src">${esc(s.source_artifact)}</div></div>`).join('')}</div></section>
    <section><h2>Today's content opportunity · historical event replay</h2>
      <div class="panel"><span class="badge b-demo_replay">historical event replay · QA blocked</span>
        <h3 style="margin:0 0 4px;font:600 18px/1.3 Georgia,serif">US Employment Situation, August 2026</h3>
        <p style="margin:0 0 8px;font-size:13.5px;color:var(--ink2)">Released 2026-09-04 08:30 ET ·
          fact pack <code>bls-employment-2026-08</code> · 51 typed facts with exact character spans.</p>
        <p style="margin:0;font-size:13.5px"><strong>Why it is not deliverable:</strong>
          the draft produced for this event is classified
          <code>qa_failed_regression_case</code>. Automated QA passed it; manual review found a
          ten-fold magnitude error, an out-of-evidence claim, a citation relation mismatch, a
          clause-attribution error and five missing mandatory facts.</p>
        <div class="src">evidence_loop/sources/packets/75155f58f5a995e3.json</div></div></section>
    <section><h2>Content production flow</h2><div class="flowwrap">
      <div class="steps" role="tablist">${M.flow.map(s =>
        `<button class="step" role="tab" aria-selected="${s.id === step}" data-step="${s.id}">
          <span class="n">${s.n}</span><span><span class="t">${esc(s.title)}</span><br>
          <span class="z">${esc(s.zh)}</span></span><span class="dot d-${s.state}"></span></button>`).join('')}</div>
      <div class="detail">${flowDetail()}</div></div></section>
    <section><h2>Persona composition</h2>${personaPanel()}</section>
    <section><h2>Evidence &amp; QA · why this draft is blocked</h2>${evidencePanel()}</section>
    <section><h2>Evergreen knowledge corpus</h2>${evergreenPanel()}</section>
    <footer>Assembled ${esc(M.generated_at)} from local artifacts.
      No generation, no network, no publication. Video ingestion:
      ${esc(M.videos?.status || 'unknown')} (${M.videos?.videos ?? 0} videos, ${M.videos?.segments ?? 0} segments).</footer>`;

  document.querySelectorAll('[data-step]').forEach(b =>
    b.onclick = () => { step = b.dataset.step; render(); });
  document.querySelectorAll('[data-persona]').forEach(b =>
    b.onclick = () => { persona = b.dataset.persona; render(); });
}

fetch('/api/demo-workbench').then(r => r.json()).then(m => { M = m; render(); })
  .catch(e => { document.getElementById('app').innerHTML = `<p style="color:#8a3143">Backend not reachable: ${esc(e.message)}</p>`; });
