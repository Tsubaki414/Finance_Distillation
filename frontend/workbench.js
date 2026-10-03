/* Content Intelligence workbench. Renders /api/intel. Never invents a value:
   anything without a local artifact is tagged illustrative or unavailable. */
const E = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const N = n => typeof n === 'number' ? n.toLocaleString('en-US') : E(n);
const tag = t => `<span class="tag t-${E(t)}">${E({ real: '真实证据', illustrative: '结构示例', unavailable: '暂不可用' }[t] || t)}</span>`;

const ICON = {
  today: 'M2 6h12M2 6v7a1 1 0 001 1h10a1 1 0 001-1V6M2 6l1.4-3h9.2L14 6M6 9h4',
  events: 'M3 3v10h10M6 10l2.5-3L11 9l2-4',
  radar: 'M8 2a6 6 0 106 6M8 8l4-4M8 5.5A2.5 2.5 0 108 10.5',
  personas: 'M8 8a2.6 2.6 0 100-5.2A2.6 2.6 0 008 8zM3 14c0-2.5 2.2-4 5-4s5 1.5 5 4',
  drafts: 'M4 2h5l3 3v9H4zM9 2v3h3M6 9h4M6 11.5h3',
  knowledge: 'M3 3h4.5a1.5 1.5 0 011.5 1.5V14a1.2 1.2 0 00-1.2-1.2H3zM13 3H8.5A1.5 1.5 0 007 4.5V14a1.2 1.2 0 011.2-1.2H13z',
  library: 'M3 13V4a1 1 0 011-1h1v10H4a1 1 0 01-1 1zM6 3h1.5v10H6zM9 3.4l1.4-.3 2 9.4-1.4.3z',
  inbox: 'M2 9h3l1 2h4l1-2h3M2 9l2-6h8l2 6v3a1 1 0 01-1 1H3a1 1 0 01-1-1z',
  runs: 'M2 8h3l2-4 2 8 2-4h3',
  quality: 'M8 2l1.9 3.9 4.3.6-3.1 3 .7 4.3L8 11.8 4.2 13.8l.7-4.3-3.1-3 4.3-.6z',
  status: 'M8 2a6 6 0 100 12A6 6 0 008 2zM8 5v3.5M8 11h.01',
  settings: 'M8 10a2 2 0 100-4 2 2 0 000 4zM13 8a5 5 0 00-.1-1l1.2-.9-1.2-2-1.4.5A5 5 0 0010 3.7L9.8 2.2H6.2L6 3.7a5 5 0 00-1.5.9L3.1 4.1l-1.2 2 1.2.9a5 5 0 000 2l-1.2.9 1.2 2 1.4-.5c.4.4 1 .7 1.5.9l.2 1.5h3.6l.2-1.5c.5-.2 1.1-.5 1.5-.9l1.4.5 1.2-2-1.2-.9c.1-.3.1-.7.1-1z',
};
// Badges count real artifacts. They were literals, and the drafts badge read 1 while three
// drafts had passed.
const NAV = () => [
  ['today', '今日情报', 'today', ''],
  ['events', '事件与内容机会', 'events', String((D?.opportunities || []).length || '')],
  ['radar', 'KOL 雷达', 'radar', ''],
  ['personas', '人设工作室', 'personas', String((A?.drafts || []).length || '')],
  ['drafts', '草稿与配图', 'drafts', String(A?.counts?.drafts_ready || '')],
  ['knowledge', '知识产品', 'knowledge',
   String((A?.evergreen?.cards || []).length ? (A.reactivation.length + A.crosslang.length) : '')],
  ['library', '资料库与更新', 'library', ''],
];
const NAV2 = [
  ['inbox', '素材收件箱', 'inbox'], ['runs', 'Pipeline Runs', 'runs'],
  ['quality', 'Quality & Evals', 'quality'], ['status', 'System Status', 'status'],
  ['settings', '设置', 'settings'],
];
const svg = d => `<svg class="ico" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="${d}"/></svg>`;

// #view/sub, so a tab is addressable and can be opened directly
const HASH = (location.hash || '').replace('#', '').split('/');
let D = null, view = (HASH[0] || 'today'), persona = 'macro', qaOpen = false, openStack = 'official', platform = 'brief';
const SEG = { market: ['US', 'CN', 'Crypto', 'Global'], lang: ['CN', 'EN', 'KR'], range: ['24h', '7d', '30d'] };
const segState = { market: 'US', lang: 'CN', range: '7d' };

function chrome() {
  document.getElementById('nav').innerHTML =
    NAV().map(([id, label, ic, b]) => `<a data-view="${id}" class="${view === id ? 'on' : ''}">${svg(ICON[ic])}${E(label)}${b ? `<span class="badge">${b}</span>` : ''}</a>`).join('')
    + `<div class="grp">Operations</div>`
    + NAV2.map(([id, label, ic]) => `<a data-view="${id}" class="${view === id ? 'on' : ''}">${svg(ICON[ic])}${E(label)}</a>`).join('');
  for (const k of Object.keys(SEG)) {
    document.getElementById(k).innerHTML = SEG[k]
      .map(v => `<button data-seg="${k}" data-val="${v}" aria-pressed="${segState[k] === v}">${v}</button>`).join('');
  }
  document.getElementById('updated').textContent = (D.data_updated_at || '').slice(0, 16).replace('T', ' ') + ' UTC';
  document.querySelectorAll('[data-view]').forEach(a => a.onclick = () => { view = a.dataset.view; render(); });
  document.querySelectorAll('[data-seg]').forEach(b => b.onclick = () => {
    segState[b.dataset.seg] = b.dataset.val; chrome();
  });
}

/* ---------------- Today ---------------- */
const arrow = d => d > 0 ? '↑' : d < 0 ? '↓' : '→';
const dcls = d => d > 0 ? 'up' : d < 0 ? 'down' : 'flat';

function pulseCard(p, lead) {
  const q = p.lead_quote;
  const langs = Object.entries(p.languages || {}).map(([k, v]) => `${k} ${v}`).join(' / ');
  return `<article class="pcard ${lead ? 'hero' : ''}" data-open="${p.opportunities ? 'opp-bls-macro' : ''}">
    <div class="ph"><span class="phase ph-${E(p.phase)}">${E(p.phase)}</span>
      <span class="delta ${dcls(p.delta_pp)}">${arrow(p.delta_pp)} ${p.delta_pp > 0 ? '+' : ''}${p.delta_pp}pp</span></div>
    <h3>${E(p.topic)}</h3>
    <div class="figs">
      <div class="fig"><b>${p.share}%</b><span>帖子占比</span></div>
      <div class="fig"><b>${N(p.posts)}</b><span>条，此前 ${N(p.posts_prior)}</span></div>
      <div class="fig"><b>${p.voice_count}</b><span>位作者</span></div>
    </div>
    ${lead && q ? `<blockquote class="lq"><span class="qw">${E(q.donor)}</span>
      <span class="qd">${E(q.date)}</span>${q.views ? `<span class="qv">${N(q.views)} views</span>` : ''}
      <p>${E(q.text)}</p></blockquote>` : ''}
    ${lead ? `<p class="why">${E(p.why_now)}</p>` : ''}
    <div class="foot"><span class="micro">${E(langs)}</span>
      ${p.opportunities ? `<span class="opp">${p.opportunities} opportunity</span>` : ''}</div>
  </article>`;
}

function today() {
  const S = D.signals, r = D.radar;
  const maxT = Math.max(...S.tickers.map(t => t.posts));
  const maxV = Math.max(...S.volume.map(v => v.posts));
  return `<div class="phead"><div>
      <h1>现在什么值得做？</h1>
      <p>跨市场的信号、KOL 观点与内容机会。</p></div>
    <div class="legend"><span class="win">Trailing ${S.window_days}d vs prior ${S.window_days}d ·
      ${N(S.posts_current)} posts · ${S.authors_active} voices</span>${tag('real')}</div></div>

  <section class="sec"><header><h2>叙事脉搏</h2>
    <span class="hint">话题占比，与上一窗口对比</span></header>
    <div class="pulse">${pulseCard(D.pulse[0], true)}
      <div class="side">${D.pulse.slice(1, 4).map(p => pulseCard(p, false)).join('')}</div></div></section>

  <section class="sec"><div class="band3">
    <div class="panel"><header><h3>讨论最多的标的</h3>${tag('real')}
      <span class="hint push">近 ${S.window_days} 天</span></header>
      <div class="body tk">${S.tickers.slice(0, 7).map(t => `<div class="trow">
        <span class="sym">${E(t.symbol)}</span>
        <span class="nm">${E(t.name)}</span>
        <span class="tb"><i data-w="${Math.round(t.posts / maxT * 62)}"></i></span>
        <span class="tn">${N(t.posts)}</span>
        <span class="td ${dcls(t.delta)}">${t.delta > 0 ? '+' : ''}${t.delta}</span>
      </div>`).join('')}</div></div>

    <div class="panel"><header><h3>即将到来的催化剂</h3>${tag('real')}
      <span class="hint push">${D.catalysts.length} 项已排期</span></header>
      <div class="body cal">${D.catalysts.map(c => `
        <div class="crow ${c.kind === 'Macro data' ? 'macro' : ''}">
          <div class="cdt"><span class="cdd">${E(c.date.slice(5))}</span>
            <span class="cdy">${c.days}d</span></div>
          <div class="cbody"><div class="cti">${E(c.title)}
            <span class="ckind ${c.kind === 'Macro data' ? 'km' : 'ke'}">${E(c.kind)}</span></div>
            <div class="cno">${E(c.note)}</div></div>
          ${c.mentions ? `<div class="cme"><b>${N(c.mentions)}</b><span>posts</span></div>` : '<div class="cme"></div>'}
        </div>`).join('')}
        <div class="calfoot">Earnings dates from ${E(D.catalyst_meta.provider)}, ${D.catalyst_meta.http_requests_last_refresh} requests, cached.
          Planning signal, confirm against issuer IR before publishing.</div>
      </div></div>

    <div class="panel"><header><h3>谁在讨论什么</h3>${tag('real')}</header>
      <div class="body">${S.topics.slice(0, 4).map(t => `<div class="vrow">
        <div class="vh"><span class="vt">${E(t.label)}</span>
          <span class="vd ${dcls(t.delta_pp)}">${arrow(t.delta_pp)} ${t.delta_pp > 0 ? '+' : ''}${t.delta_pp}pp</span></div>
        <div class="vw">${t.voices.map(v => `<span class="vp">${E(v.donor)} <b>${v.posts}</b></span>`).join('')}</div>
      </div>`).join('')}
      <div class="spark">${S.volume.map(v => `<i data-h="${Math.round(v.posts / maxV * 26)}" title="${E(v.date)}: ${v.posts}"></i>`).join('')}
        <span class="sl">每日发帖量</span></div>
      </div></div></div></section>

  <section class="sec"><div class="pipebar">
    <div class="pb"><span class="pbn">${D.pipeline.qa_gates.regression_caught}/${D.pipeline.qa_gates.regression_expected}</span>
      <span class="pbl">QA 闸门回归命中</span><span class="pbd">七层闸门重放冻结稿件</span></div>
    <div class="pb"><span class="pbn">${D.pipeline.profiles.eligible_donors.length}</span>
      <span class="pbl">合格 donor</span><span class="pbd">画像通道 ${E(D.pipeline.profiles.active_channel)} · 时点截断</span></div>
    <div class="pb"><span class="pbn">${N(D.pipeline.principles.total)}</span>
      <span class="pbl">Evergreen 候选原则</span><span class="pbd">拒绝 ${D.pipeline.principles.rejected} 条未通过溯源</span></div>
    <div class="pb"><span class="pbn">${N(D.evergreen_summary.independent_sources)}</span>
      <span class="pbl">独立来源</span><span class="pbd">语义去重后</span></div>
  </div></section>

  <section class="sec gaps"><div class="gaprow">
    <div class="gap">${svg(ICON.status)}<div><b>${E(r.propagation.headline)}</b><span>${E(r.propagation.detail)}</span></div></div>
    <div class="gap">${svg(ICON.status)}<div><b>${E(r.stance.headline)}</b><span>${E(r.stance.detail)}</span></div></div>
    <div class="gap">${svg(ICON.status)}<div><b>${E(r.language_split.headline)}</b><span>${E(r.language_split.detail)}</span></div></div>
  </div></section>

  <section class="sec"><header><h2>内容机会队列</h2>
    <span class="hint">按当前实际可生产程度排序</span></header>
    <div class="oq">${D.opportunities.map(o => `
      <article class="opp">
        <div><div class="lane">${E(o.lane)}</div><h3>${E(o.headline)}</h3>
          <p class="why">${E(o.why_now)}</p>
          <div class="chips">${tag(o.evidence)}
            <span class="chip k">${E(o.persona.label)}</span>
            ${o.platforms.map(p => `<span class="chip">${E(p)}</span>`).join('')}</div></div>
        <div class="srcs">
          <span class="off">Facts <b>${N(o.sources.official_facts)}</b></span>
          <span>KOL <b>${N(o.sources.kol_voices)}</b></span>
          <span>Evergreen <b>${N(o.sources.evergreen)}</b></span>
          <span>Research <b>${N(o.sources.institutional)}</b></span></div>
        <div class="act"><span class="tag t-${o.readiness.tone === 'blocked' ? 'blocked' : 'unavailable'}">${E(o.readiness.label)}</span>
          <button class="btn ${o.open ? '' : 'ghost'}" ${o.open ? 'data-open="' + E(o.id) + '"' : 'disabled'}>进入工作区</button></div>
      </article>`).join('')}</div></section>`;
}

/* ---------------- Workspace ---------------- */
function workspace() {
  const w = D.workspace, s = w.source_stack, c = w.canvas, ct = w.controls;
  const p = ct.personas.find(x => x.id === persona) || ct.personas[0];
  const group = (key, g, inner) => `<div class="sgroup">
    <button data-stack="${key}">${svg(ICON.knowledge)}<span class="lbl">${E(g.label)}</span>
      <span class="cnt">${g.count !== undefined ? N(g.count) : ''}</span></button>
    ${openStack === key ? `<div class="inner">${E(g.detail)}${inner || ''}</div>` : ''}</div>`;

  return `<div class="crumb"><a data-view="today">今日情报</a> › <span>内容机会工作区</span></div>
  <div class="phead"><div><h1>${E(w.title)}</h1>
      <p>${E(w.lane)} · released ${E((w.released_at || '').slice(0, 10))} · <b>${E(w.banner.label)}</b>. ${E(w.banner.detail)}</p></div>
    <div class="legend">${tag('real')}</div></div>

  <div class="ws3">
    <div class="stack">
      ${group('official', s.official, `<div class="flist">${s.official.items.map(f =>
        `<div class="f"><code>${E(f.id)}</code><span class="v">${N(f.value)}<span class="unit"> ${E(f.unit === 'persons' ? '' : f.unit)}</span></span></div>`).join('')}</div>`)}
      ${group('kol', s.kol, `<div class="flist">${s.kol.items.map(i =>
        `<div class="f"><code>${E(i.donor)}</code><span class="v">${i.score}</span></div>`).join('')}
        <div class="micro mt5">All posts predate the release.</div></div>`)}
      ${group('institutional', s.institutional, `<div class="mt6">${tag('unavailable')}</div>`)}
      ${group('evergreen', s.evergreen, `<div class="mt6">${tag('unavailable')}</div>`)}
      ${group('provenance', s.provenance, '')}
    </div>

    <div class="canvas">
      <div class="lab">主问题</div>
      <div class="q">${E(c.question || 'not set')}</div>
      <div class="lab">可选角度</div>
      <div class="angles">${c.angles.map(a =>
        `<button class="angle ${a.state.startsWith('missing') ? 'miss' : ''}">${E(a.label)}<span class="st">${E(a.state)}</span></button>`).join('')}</div>
      <div class="lab">反方观点</div>
      <p class="prose flat">${E(c.counter || 'not set')}</p>
      <div class="lab">失效条件</div>
      <p class="prose flat">${E(c.invalidation || 'not set')}</p>
      <div class="lab">Draft <span class="tag t-blocked ml6">Blocked</span></div>
      <div class="prose">${c.draft.sentences.map(s =>
        `<div class="s">${E(s.text)}<span class="ids">${E(s.fact_ids.join(' '))}</span></div>`).join('')}</div>
      <div class="lab">平台内容包</div>
      <div class="pf">${c.platforms.map(pl =>
        `<button data-platform="${E(pl.id)}" aria-pressed="${platform === pl.id}">${E(pl.label)}<span class="st">${E(pl.state)}</span></button>`).join('')}</div>
      <div class="lab">视觉方案</div>
      <div class="note">${svg(ICON.quality)}<div><b>${E(c.visual.recommended)}.</b> ${E(c.visual.reason)}
        <div class="mt5">${tag('unavailable')} ${E(c.visual.status)}</div></div></div>
    </div>

    <div class="ctrl">
      <div class="panel"><header><h3>人设</h3></header><div class="body">
        <div class="pcards">${ct.personas.map(x =>
          `<button class="psel" data-persona="${E(x.id)}" aria-pressed="${x.id === persona}">
            <div class="zh">${E(x.zh)}</div><div class="en">${E(x.en)}</div></button>`).join('')}</div>
        <div class="lab">Donor 角色</div>
        <div class="roles">${p.roles.map(r =>
          `<div class="role"><span class="rn">${E(r.role)}</span><span class="rv">${E(r.status)}</span></div>`).join('')}</div>
        <div class="note mt10">${svg(ICON.status)}<div>Planned donors exist but no role assignment ran for this draft.</div></div>
      </div></div>

      <div class="panel"><header><h3>信号</h3></header><div class="body">
        <dl class="kv"><dt>Freshness</dt><dd>${E(ct.freshness.label)}</dd>
          <dt>Official facts</dt><dd>${E(ct.coverage.official)}</dd>
          <dt>KOL coverage</dt><dd>${E(ct.coverage.kol)}</dd>
          <dt>Evergreen</dt><dd>${E(ct.coverage.evergreen)}</dd></dl></div></div>

      <div class="qabar"><button data-qa="1">${svg(ICON.status)} QA 闸门 · ${ct.qa.issue_count} 项拦截
        <span class="push nb">${qaOpen ? '收起' : '展开'}</span></button>
        ${qaOpen ? `<div class="inner">${ct.qa.findings.map(f => `
          <div class="finding"><div class="ft">${E(f.type.replace(/_/g, ' '))}</div>
            <div class="fd">${E(f.note)}</div>
            ${f.draft_display ? `<div class="cmp"><span>Draft wrote <span class="bad">${E(f.draft_display)}</span></span>
              <span>Source says <span class="good">${E(f.expected_display)}</span></span></div>` : ''}
            ${f.missing_fact_ids ? `<div class="cmp"><span>Missing <span class="bad">${E(f.missing_fact_ids.join(', '))}</span></span></div>` : ''}
          </div>`).join('')}
          <div class="gatelist">${(ct.qa.gates || []).map(g => `<div class="gl"><span class="gn">L${g.layer}</span>${E(g.name)}</div>`).join('')}</div>
          <div class="micro2">${E(ct.qa.model)}</div>
        </div>` : ''}</div>
    </div></div>`;
}

/* ---------------- other views ---------------- */
function personasView() {
  return `<div class="phead"><div><h1>人设工作室</h1>
    <p>Composite voices built from separate donor roles. Sliders unlock only where a measured range exists.</p></div></div>
  <div class="pulse">${D.personas.map(p => `<article class="pcard">
    <div class="ph">${tag('real')}</div><h3>${E(p.zh)}</h3>
    <p class="why">${E(p.question || '')}</p>
    <div class="split"><div class="row"><span class="k">Donors</span><span>${E(p.planned_donors.join(', ') || 'none')}</span></div></div>
    <div class="roles mt8">${p.roles.map(r =>
      `<div class="role"><span class="rn">${E(r.role)}</span><span class="rv">${E(r.status)}</span></div>`).join('')}</div>
  </article>`).join('')}</div>`;
}
/* The earlier Knowledge Products view rendered each principle's evidence_quote in a
   <blockquote>. Every candidate carries direct_quote_allowed:false, so that surface was
   publishing third-party wording the rest of the pipeline refuses to reproduce. It is
   replaced by the view below, which shows the restatement and the attribution only. */

function placeholder(title, msg) {
  return `<div class="phead"><div><h1>${E(title)}</h1><p>${E(msg)}</p></div></div>
    <div class="panel"><div class="empty">Not built in this round.<br>
      <button class="btn ghost mt10" data-view="today">Back to Today</button></div></div>`;
}


/* ---------------- Drafts & Visuals / Knowledge Products ----------------
   Real artifacts from steps 2-7 of the delivery plan. Every status shown is copied from the
   artifact file; nothing is recomputed here, so this surface cannot look healthier than the
   pipeline actually is. */

let A = null, aDraft = null, aPack = 'x_post', aCard = null;
let kTab = (HASH[0] === 'knowledge' && HASH[1]) || 'evergreen';

const st = (v, good = 'passed') => v == null ? '' :
  `<span class="st ${v === good || v === 'ready_for_pipeline' ? 'ok' : 'no'}">${E(v)}</span>`;

function factRefs(ids) {
  return (ids || []).map(f => `<span class="chip mono">${E(f)}</span>`).join('');
}

function draftsView() {
  if (!A) return `<div class="phead"><div><h1>草稿与配图</h1></div></div>
    <div class="panel"><div class="empty">Loading artifacts…</div></div>`;
  const ds = A.drafts || [];
  if (!ds.length) return placeholder('草稿与配图', '尚无稿件产物。') + '<p><a href="/localization-review">打开内容审核与改稿记录</a></p>';
  const cur = ds.find(d => d.id === aDraft) || ds[0];
  const vis = (A.visuals || []).find(v => v.draft_id === cur.id);
  const packs = (A.packages || []).filter(p => p.draft_id === cur.id);
  const pack = packs.find(p => p.form === aPack) || packs[0];
  const c = A.counts || {};

  return `<div class="phead"><div><h1>草稿与配图</h1>
      <p>按账号和目标语言审核稿件；译文与轻编稿可逐段对照原文。模型检查通过后仍待人工确认。</p><a href="/localization-review">内容审核与改稿记录</a></div>
    <div class="stat-row" style="margin-left:auto">
      <div class="stat"><b>${c.drafts_ready}/${c.drafts_total}</b><span>稿件过闸</span></div>
      <div class="stat"><b>${c.packages_ready}/${c.packages_total}</b><span>内容包过闸</span></div>
      <div class="stat"><b>${A.traceback?.traced ?? '—'}/${A.traceback?.fact_bearing_sampled ?? '—'}</b>
        <span>抽样可回溯原文</span></div>
    </div></div>

  <div class="asset-grid">
    <div class="asset-list">
      ${ds.map(d => `<button class="acard ${d.id === cur.id ? 'on' : ''}" data-draft="${E(d.id)}">
        <div class="t">${E(d.persona_name)}</div>
        <div class="s">${E(d.title || '')}</div>
        <div class="s" style="margin-top:6px">${st(d.content_status)}
          ${d.origin === 'localization_v1' ? `<span class="chip">${E(d.account_id || '未路由')} · ${E(d.source_language)} → ${E(d.lang || '—')}</span>` :
          `<span class="chip mono">槽位 ${d.slots?.placed}/${d.slots?.total}</span><span class="chip mono">${d.sentences} 句</span>`}</div>
      </button>`).join('')}
    </div>

    <div style="display:flex;flex-direction:column;gap:14px">
      <div class="panel"><header><h3>${E(cur.title || '')}</h3>
        <span>${st(cur.qa_status)} ${st(cur.form_status)}</span></header>
        <div class="body">
          ${cur.origin === 'localization_v1' ? `
          <p>${E(cur.account_id || '未路由')} · ${E(cur.source_language)} → ${E(cur.lang || '—')} · 人审：${E(cur.review_status)}</p>
          <p class="fine">${E(cur.why)}</p>
          <p class="fine">来源：${E(cur.provenance?.author_name)} · ${E(cur.provenance?.url)}</p>
          <div style="overflow-x:auto"><table class="localization-comparison"><thead><tr><th>选中原文</th><th>忠实译文</th><th>轻编稿</th></tr></thead><tbody>
          ${(cur.comparison || []).map(r => `<tr><td>${E(r.source)}</td><td>${E(r.translation)}</td><td>${E(r.localization)}</td></tr>`).join('')}
          </tbody></table></div>
          ${(cur.edits || []).map(e => `<p class="fine">${E(e.paragraph_id)}：${E(e.reason)}</p>`).join('')}` : `
          <dl class="kv left" style="margin-bottom:10px">
            <dt>必含事实覆盖</dt><dd>${cur.must_include_coverage}</dd>
            <dt>闸门版本</dt><dd class="mono">${E(cur.gate_version)} · ${E(cur.form_version)}</dd>
            <dt>donor 角色</dt><dd class="mono">${E(Object.entries(cur.roles || {})
              .filter(([, v]) => v).map(([k, v]) => k + ':' + v).join(' '))}</dd>
            <dt>profile 通道</dt><dd class="mono">${E(cur.profile_channel)}</dd>
            <dt>生成尝试</dt><dd>${cur.attempts}</dd>
          </dl>`}
          ${cur.blocking.length ? `<div class="fine" style="color:#b3261e">
            ${cur.blocking.map(b => E(b.code + ': ' + b.detail)).join('<br>')}</div>` : ''}
          ${cur.ledger.map(r => `<div class="sentence">${E(r.text)}
            <div class="src">${factRefs(r.fact_ids)}
              ${r.proposed_thresholds.length ? `<span class="chip">作者阈值（非数据）
                ${E(r.proposed_thresholds.join('、'))}</span>` : ''}
              <a href="${E(r.primary_url)}" target="_blank" rel="noreferrer">原始来源</a></div>
          </div>`).join('')}
        </div></div>

      ${vis ? `<div class="panel"><header><h3>配图</h3>
        <span class="chip">${E(vis.chart_kind)}</span></header><div class="body">
        <p class="fine" style="margin-bottom:8px">${E(vis.brief?.why || '')}</p>
        <div class="figure"><img src="${E(vis.svg_url)}" alt="${E(vis.brief?.alt_text || '')}"></div>
        <p class="fine" style="margin-top:8px">图上每个数字都绑定 fact_id，由代码从事实包渲染；
          ${E(vis.rendered_by)}</p>
        <dl class="kv left" style="margin-top:8px">${(vis.numbers_drawn || []).map(n =>
          `<dt class="mono">${E(n.fact_id)}</dt><dd>${E(n.drawn_as)}　
            <span class="fine mono">字符 ${n.char_span[0]}–${n.char_span[1]}</span></dd>`).join('')}</dl>
        </div></div>` : ''}

      ${pack ? `<div class="panel"><header><h3>平台内容包</h3>
        <span>${st(pack.content_status)}</span></header><div class="body">
        <div class="tabs">${packs.map(p => `<button data-pack="${E(p.form)}"
          aria-pressed="${p.form === pack.form}">${E(p.form_name)}</button>`).join('')}</div>
        <p class="fine" style="margin-bottom:8px">${pack.measured} ${E(pack.measure)}
          · ${pack.units} ${E(pack.unit_name)}</p>
        ${(pack.segments || []).map(s => `<div class="sentence">${E(s.text)}
          <div class="src">${factRefs(s.fact_ids)}
            ${s.proposed_thresholds.length ? `<span class="chip">作者阈值（非数据）</span>` : ''}
          </div></div>`).join('')}
        <div style="margin-top:10px" class="fine"><b>失效条件</b><br>
          ${(pack.conditions?.invalidation || []).map(E).join('<br>')}</div>
        <div style="margin-top:8px" class="fine"><b>来源包</b>（${(pack.source_pack || []).length} 条事实，
          每条可按字符区间回原文）<br>
          ${(pack.source_pack || []).slice(0, 4).map(s =>
            `<span class="mono">${E(s.fact_id)} 字符 ${s.char_span[0]}–${s.char_span[1]}
             ${s.quote_resolves ? '✓' : '✗'}</span>`).join('<br>')}
        </div>
      </div></div>` : ''}
    </div>
  </div>`;
}

function knowledgeView() {
  if (!A) return `<div class="phead"><div><h1>知识产品</h1></div></div>
    <div class="panel"><div class="empty">Loading artifacts…</div></div>`;
  const ev = A.evergreen || {}, re = (A.reactivation || [])[0], cl = (A.crosslang || [])[0];
  const tabs = [['evergreen', '交易心法（Evergreen）'], ['reactivate', '事件重新激活'],
                ['crosslang', '跨语言版本']];
  let body = '';

  if (kTab === 'evergreen' && ev.available) {
    const card = (ev.cards || []).find(c => c.principle_id === aCard) || (ev.cards || [])[0];
    body = `<div class="panel"><header><h3>原则卡</h3>
      <span class="st wait">待人工审核</span></header><div class="body">
      <p class="fine" style="margin-bottom:10px">
        全部候选 <span class="mono">direct_quote_allowed: false</span>，
        因此卡片只呈现转述并注明出处，不含任何作者原话（已逐条比对，直接引用数 ${ev.direct_quotes_used}）。</p>
      <div class="cards-row">${(ev.cards || []).slice(0, 6).map(c =>
        `<div class="figure"><img src="${E(c.svg_url)}" alt="${E(c.statement)}"></div>`).join('')}</div>
      </div></div>

      <div class="panel" style="margin-top:14px"><header><h3>语料与扣留</h3></header><div class="body">
      <div class="stat-row">
        <div class="stat"><b>${ev.candidates}</b><span>候选原则</span></div>
        <div class="stat"><b>${ev.span_resolves_in_file}/${ev.eligible}</b><span>可回原文字符区间</span></div>
        <div class="stat"><b>${ev.held_back}</b><span>因二手合录扣留</span></div>
        <div class="stat"><b>${ev.four_part_and_traceable}</b><span>四要素齐全</span></div>
      </div>
      <p class="fine" style="margin-top:10px"><b>反例字段审计</b>：
        ${Object.entries(ev.counterexample_audit?.kinds || {}).map(([k, v]) =>
          `${E(k)} ${v}`).join('　·　')}。
        以「原文提到…」开头的是抽取器在复述原文，不是反例，已排除出解释帖。</p>
      <p class="fine" style="margin-top:6px"><b>扣留</b>：
        ${(ev.held_back_detail || []).slice(0, 1).map(h => E(h.path + ' — ' + h.why)).join('')}
        （共 ${ev.held_back} 条）</p>
      </div></div>

      <div class="panel" style="margin-top:14px"><header><h3>解释帖 · 原则 + 适用条件 + 失效条件 + 反例</h3>
      </header><div class="body"><div class="md">${E((ev.explainers?.[0]?.markdown_text) || '')}</div>
      </div></div>`;
  } else if (kTab === 'reactivate' && re) {
    body = `<div class="panel"><header><h3>${E(re.title || '')}</h3>
      <span>${st(re.qa_status)} ${st(re.principles_status)} ${st(re.content_status)}</span>
      </header><div class="body">
      <p class="fine" style="margin-bottom:10px">原则来自检索而非现写；
        检索模型 <span class="mono">${E(re.retrieval?.embedding_model || '')}</span>，
        候选池已剔除二手合录。母稿 <span class="mono">${E(re.parent_draft_id)}</span> 承担必含事实全覆盖。</p>
      ${(re.principles || []).map(p => `<div class="sentence">
        <b>${E(p.statement)}</b>
        <div class="src"><span class="chip mono">检索分 ${p.retrieval_score}</span>
          <span class="chip">${E(p.attribution)}</span>
          <span class="chip">${E(p.review)}</span></div></div>`).join('')}
      <div class="md" style="margin-top:12px">${E(re.markdown_text || '')}</div>
      </div></div>`;
  } else if (kTab === 'crosslang' && cl) {
    const a = cl.alignment || {};
    body = `<div class="panel"><header><h3>${E(cl.title || '')}</h3>
      <span>${st(cl.qa_status)} ${st(cl.crosslang_status)} ${st(cl.content_status)}</span>
      </header><div class="body">
      <div class="stat-row" style="margin-bottom:10px">
        <div class="stat"><b>${a.zh_fact_count}→${a.en_fact_count}</b><span>事实对齐</span></div>
        <div class="stat"><b>${(a.dropped_in_english || []).length}</b><span>丢失</span></div>
        <div class="stat"><b>${(a.added_in_english || []).length}</b><span>新增</span></div>
      </div>
      <p class="fine" style="margin-bottom:10px">${E(cl.method || '')}</p>
      <table class="mono" style="width:100%;border-collapse:collapse;font-size:11.5px">
        <tr><th style="text-align:left">fact</th><th style="text-align:left">中文</th>
          <th style="text-align:left">English</th></tr>
        ${(a.facts || []).map(r => `<tr>
          <td style="padding:3px 0">${E(r.fact_id)}</td><td>${E(r.zh || '—')}</td>
          <td>${E(r.en || '—')}</td></tr>`).join('')}
      </table>
      <div style="margin-top:12px">${(cl.sentences || []).map(s => `<div class="sentence">
        ${E(s.text)}<div class="src"><span class="chip">${E(s.kind_en)}</span></div></div>`).join('')}</div>
      </div></div>`;
  } else {
    body = `<div class="panel"><div class="empty">该产物尚未生成。</div></div>`;
  }

  return `<div class="phead"><div><h1>知识产品</h1>
    <p>Evergreen 心法、事件重新激活与跨语言版本，全部标注出处与审核状态。</p></div></div>
    <div class="tabs">${tabs.map(([k, l]) =>
      `<button data-ktab="${k}" aria-pressed="${kTab === k}">${E(l)}</button>`).join('')}</div>
    ${body}`;
}

function render() {
  chrome();
  const el = document.getElementById('page');
  if (view === 'today') el.innerHTML = today();
  else if (view === 'workspace') el.innerHTML = workspace();
  else if (view === 'personas') el.innerHTML = personasView();
  else if (view === 'knowledge') el.innerHTML = knowledgeView();
  else if (view === 'drafts') el.innerHTML = draftsView();
  else if (view === 'status' || view === 'quality') { location.href = '/system-status'; return; }
  else if (view === 'events') el.innerHTML = today();
  else el.innerHTML = placeholder(NAV().concat(NAV2).find(n => n[0] === view)?.[1] || view,
    'This surface is defined in the information architecture but has no data behind it yet.');

  el.querySelectorAll('[data-w]').forEach(b => { b.style.width = b.dataset.w + 'px'; });
  el.querySelectorAll('[data-h]').forEach(b => { b.style.height = Math.max(2, +b.dataset.h) + 'px'; });
  el.querySelectorAll('[data-open]').forEach(b => { if (b.dataset.open) b.onclick = () => { view = 'workspace'; render(); window.scrollTo(0, 0); }; });
  el.querySelectorAll('[data-view]').forEach(b => b.onclick = () => { view = b.dataset.view; render(); });
  el.querySelectorAll('[data-persona]').forEach(b => b.onclick = () => { persona = b.dataset.persona; render(); });
  el.querySelectorAll('[data-stack]').forEach(b => b.onclick = () => { openStack = openStack === b.dataset.stack ? '' : b.dataset.stack; render(); });
  el.querySelectorAll('[data-platform]').forEach(b => b.onclick = () => { platform = b.dataset.platform; render(); });
  el.querySelectorAll('[data-qa]').forEach(b => b.onclick = () => { qaOpen = !qaOpen; render(); });
  el.querySelectorAll('[data-draft]').forEach(b => b.onclick = () => { aDraft = b.dataset.draft; render(); });
  el.querySelectorAll('[data-pack]').forEach(b => b.onclick = () => { aPack = b.dataset.pack; render(); });
  el.querySelectorAll('[data-ktab]').forEach(b => b.onclick = () => {
    kTab = b.dataset.ktab; history.replaceState(null, '', '#knowledge/' + kTab); render(); });
}

Promise.all([fetch('/api/intel').then(r => r.json()),
             fetch('/api/assets').then(r => r.json()).catch(() => null)])
  .then(([d, a]) => { D = d; A = a; render(); })
  .catch(e => { document.getElementById('page').innerHTML = `<div class="empty">Backend not reachable: ${E(e.message)}</div>`; });
