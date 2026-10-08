// One chart page for live/media_real.py, rendered offline in headless Chromium with TradingView Lightweight Charts
// (Apache-2.0). window.C is the job config; every number in it comes from a fetch made by live/charts.py /
// live/media_real.py. Styles: tv (desktop chart screenshot), mobile (phone exchange / broker app screenshot),
// panel (data-series panel), table (perp funding / OI table). Drawings: only the levels the draft names.
(function () {
  const C = window.C;
  const L = C.theme === 'light';
  const P = Object.assign(L ? {
    bg: '#ffffff', fg: '#131722', dim: '#787b86', grid: '#f0f3fa', border: '#e0e3eb', bar: '#ffffff',
    up: '#089981', down: '#f23645', hover: '#f0f3fa', icon: '#131722',
  } : {
    bg: C.dark_bg || '#131722', fg: '#d1d4dc', dim: '#787b86', grid: C.dark_grid || '#1e222d', border: '#2a2e39',
    bar: C.dark_bg || '#131722', up: '#089981', down: '#f23645', hover: '#2a2e39', icon: '#d1d4dc',
  }, C.palette || {});
  const root = document.getElementById('root');
  document.body.style.background = P.bg;
  document.body.style.color = P.fg;
  const el = (tag, css, html) => { const e = document.createElement(tag); if (css) e.style.cssText = css; if (html !== undefined) e.innerHTML = html; return e; };
  const fmt = (v, d) => {
    if (d === null) d = undefined;
    if (v === null || v === undefined || !isFinite(v)) return '—';
    if (d === undefined) d = Math.abs(v) >= 1000 ? 2 : Math.abs(v) >= 1 ? (Math.abs(v) >= 100 ? 2 : 3) : 5;
    return Number(v).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
  };
  const big = (v) => {
    const a = Math.abs(v);
    if (a >= 1e12) return (v / 1e12).toFixed(2) + 'T';
    if (a >= 1e9) return (v / 1e9).toFixed(2) + 'B';
    if (a >= 1e6) return (v / 1e6).toFixed(2) + 'M';
    if (a >= 1e3) return (v / 1e3).toFixed(2) + 'K';
    return fmt(v, 2);
  };
  const icon = (d, size) => `<svg width="${size || 28}" height="${size || 28}" viewBox="0 0 28 28" fill="none" stroke="${P.icon}" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" style="opacity:.85">${d}</svg>`;
  const info = { style: C.style, levels_drawn: [] };
  window.__chartInfo = info;

  // ------------------------------------------------------------ chart helpers
  function makeChart(host, opts) {
    const chart = LightweightCharts.createChart(host, Object.assign({
      width: host.clientWidth, height: host.clientHeight,
      layout: { background: { type: 'solid', color: P.bg }, textColor: P.fg, fontSize: opts.fontSize || 12,
        fontFamily: opts.font || '-apple-system, BlinkMacSystemFont, "Trebuchet MS", Roboto, Ubuntu, sans-serif',
        attributionLogo: false },
      grid: { vertLines: { color: P.grid, visible: opts.vgrid !== false }, horzLines: { color: P.grid } },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.08, bottom: opts.volume ? 0.22 : 0.06 } },
      leftPriceScale: { visible: !!opts.left, borderVisible: false },
      timeScale: { borderVisible: !!opts.timeBorder, borderColor: P.border, rightOffset: opts.rightOffset || 6,
        barSpacing: opts.barSpacing || 6, timeVisible: !!opts.timeVisible, secondsVisible: false },
      crosshair: { mode: 1, vertLine: { visible: false, labelVisible: false }, horzLine: { visible: false, labelVisible: false } },
      handleScroll: false, handleScale: false,
      localization: { locale: 'en-US', priceFormatter: opts.priceFormatter || ((v) => fmt(v, C.precision)) },
    }, opts.extra || {}));
    return chart;
  }
  function candles(chart, opts) {
    const s = chart.addCandlestickSeries({ upColor: opts.up || P.up, downColor: opts.down || P.down,
      borderUpColor: opts.up || P.up, borderDownColor: opts.down || P.down, wickUpColor: opts.up || P.up,
      wickDownColor: opts.down || P.down, priceLineVisible: true, lastValueVisible: true,
      priceFormat: { type: 'price', precision: C.precision, minMove: Math.pow(10, -C.precision) } });
    s.setData(C.candles);
    if (opts.volume) {
      const v = chart.addHistogramSeries({ priceScaleId: 'vol', priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false });
      chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 }, visible: false });
      const up = (opts.up || P.up), dn = (opts.down || P.down);
      v.setData(C.candles.map((c) => ({ time: c.time, value: c.volume || 0, color: (c.close >= c.open ? up : dn) + (L ? '66' : '80') })));
    }
    (opts.ma || []).forEach((m) => {
      const l = chart.addLineSeries({ color: m.color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
      l.setData(m.data);
    });
    return s;
  }
  // Hand-placed drawings in an SVG over the chart: a horizontal ray per level from the bar where price last
  // touched it, and (two levels named) a rectangle zone between them over the recent bars.
  function drawLevels(host, chart, series, opts) {
    const lv = C.levels || [];
    if (!lv.length) return;
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('width', host.clientWidth); svg.setAttribute('height', host.clientHeight);
    svg.style.cssText = 'position:absolute;left:0;top:0;pointer-events:none;overflow:visible;z-index:5';
    const plotW = host.clientWidth - chart.priceScale('right').width();
    const ts = chart.timeScale();
    const add = (tag, attrs) => { const e = document.createElementNS('http://www.w3.org/2000/svg', tag); Object.entries(attrs).forEach(([k, v]) => e.setAttribute(k, v)); svg.appendChild(e); return e; };
    if (C.zone) {
      const y1 = series.priceToCoordinate(C.zone.top), y2 = series.priceToCoordinate(C.zone.bottom);
      const x1 = ts.timeToCoordinate(C.zone.from_time);
      if (y1 !== null && y2 !== null && x1 !== null) {
        add('rect', { x: x1, y: Math.min(y1, y2), width: Math.max(10, plotW - x1 - 4), height: Math.abs(y2 - y1),
          fill: C.zone.color + '26', stroke: C.zone.color, 'stroke-width': 1 });
        info.zone = [C.zone.bottom, C.zone.top];
      }
    }
    lv.forEach((l) => {
      const y = series.priceToCoordinate(l.price);
      let x = ts.timeToCoordinate(l.from_time);
      if (y === null) return;
      if (x === null) x = plotW * 0.55;
      add('line', { x1: x, y1: y, x2: l.ray === false ? x + plotW * 0.3 : plotW, y2: y, stroke: l.color,
        'stroke-width': l.width || 1, 'stroke-dasharray': l.dash ? '6 4' : '' });
      if (l.anchor_dot) add('circle', { cx: x, cy: y, r: 3, fill: P.bg, stroke: l.color, 'stroke-width': 1.5 });
      if (l.label) {
        const t = add('text', { x: plotW - 8, y: y - 5, fill: l.color, 'font-size': opts.labelSize || 12, 'text-anchor': 'end',
          'font-family': opts.font || 'Roboto, sans-serif', 'font-weight': '500', 'paint-order': 'stroke', stroke: P.bg, 'stroke-width': 3 });
        t.textContent = l.label;
      }
      info.levels_drawn.push(l.price);
    });
    host.appendChild(svg);
  }

  // ------------------------------------------------------------ TradingView-like desktop screenshot
  function tv() {
    root.style.cssText = `width:${C.w}px;height:${C.h}px;display:flex;flex-direction:column;background:${P.bg};font-family:-apple-system,BlinkMacSystemFont,"Trebuchet MS",Roboto,Ubuntu,sans-serif`;
    if (C.chrome.top) {
      const items = C.intervals.map((i) => `<span style="padding:4px 7px;border-radius:4px;${i === C.interval_label ? `background:${P.hover};` : ''}">${i}</span>`).join('');
      const bar = el('div', `height:38px;display:flex;align-items:center;gap:2px;padding:0 8px;border-bottom:1px solid ${P.border};font-size:13px;color:${P.fg};background:${P.bar}`,
        `${C.chrome.symbol_box ? `<span style="display:flex;align-items:center;gap:6px;padding:4px 8px;font-weight:600">${icon('<circle cx="14" cy="14" r="5"/><path d="M18 18l4 4"/>', 18)}${C.ticker}</span><span style="width:1px;height:20px;background:${P.border};margin:0 4px"></span>` : ''}${items}<span style="width:1px;height:20px;background:${P.border};margin:0 6px"></span>${icon('<rect x="8" y="9" width="4" height="9"/><path d="M10 6v3M10 18v3"/><rect x="16" y="7" width="4" height="8"/><path d="M18 4v3M18 15v4"/>')}<span style="width:1px;height:20px;background:${P.border};margin:0 6px"></span>${icon('<path d="M6 20l5-7 4 4 7-10"/>')}<span>${C.lang === 'zh' ? '指标' : 'Indicators'}</span>`);
      root.appendChild(bar);
    }
    const body = el('div', 'flex:1;display:flex;min-height:0');
    root.appendChild(body);
    if (C.chrome.left) {
      const glyphs = ['<path d="M14 6v16M6 14h16"/>', '<path d="M7 21L21 7"/><circle cx="7" cy="21" r="1.6"/><circle cx="21" cy="7" r="1.6"/>',
        '<path d="M6 8h16M6 12h16M6 16h16M6 20h16"/>', '<path d="M7 19c3-9 6 2 9-6s4-2 5-4"/>', '<path d="M9 7h10M14 7v14"/>',
        '<path d="M7 20l13-13M10 20l-3 0 0-3"/>', '<circle cx="12" cy="12" r="5"/><path d="M16 16l5 5"/>', '<path d="M9 13V9a5 5 0 0110 0v4"/><rect x="7" y="13" width="14" height="9" rx="1"/>', '<path d="M8 9h12M11 9V6h6v3M9 9l1 13h8l1-13"/>'];
      const lt = el('div', `width:52px;border-right:1px solid ${P.border};display:flex;flex-direction:column;align-items:center;gap:10px;padding-top:10px;background:${P.bar}`,
        glyphs.map((g) => icon(g)).join(''));
      body.appendChild(lt);
    }
    const host = el('div', 'flex:1;position:relative;min-width:0');
    body.appendChild(host);
    const chart = makeChart(host, { volume: C.volume, barSpacing: C.bar_spacing, timeVisible: C.intraday, rightOffset: C.right_offset });
    const s = candles(chart, { volume: C.volume, ma: C.ma });
    chart.timeScale().scrollToRealTime();
    // legend over the chart, like TradingView
    const last = C.candles[C.candles.length - 1], prev = C.candles[C.candles.length - 2] || last;
    const col = last.close >= last.open ? P.up : P.down;
    const chg = last.close - prev.close, pct = chg / prev.close * 100;
    const ohlc = ['O', 'H', 'L', 'C'].map((k, i) => `<span style="color:${P.fg}">${k}</span><span style="color:${col};margin-right:6px">${fmt([last.open, last.high, last.low, last.close][i], C.precision)}</span>`).join('');
    const leg = el('div', `position:absolute;left:10px;top:8px;z-index:3;font-size:${C.legend_size || 14}px;line-height:1.55;color:${P.fg};pointer-events:none`,
      `<div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">${C.coin_dot ? `<span style="width:16px;height:16px;border-radius:50%;background:${C.coin_dot};display:inline-block"></span>` : ''}<span>${C.title}</span><span style="color:${P.dim}">·</span><span>${C.interval_label}</span><span style="color:${P.dim}">·</span><span>${C.venue}</span><span style="width:8px;height:8px;border-radius:50%;background:${C.intraday ? P.up : P.dim};display:inline-block;margin:0 4px"></span><span style="font-size:13px">${ohlc}<span style="color:${col}">${chg >= 0 ? '+' : '−'}${fmt(Math.abs(chg), C.precision)} (${pct >= 0 ? '+' : '−'}${Math.abs(pct).toFixed(2)}%)</span></span></div>` +
      (C.volume ? `<div style="font-size:13px"><span>Vol${C.base ? ' · ' + C.base : ''}</span> <span style="color:${col}">${big(last.volume || 0)}</span></div>` : '') +
      (C.ma || []).map((m) => `<div style="font-size:13px"><span>${m.name}</span> <span style="color:${m.color}">${fmt(m.data[m.data.length - 1].value, C.precision)}</span></div>`).join(''));
    host.appendChild(leg);
    return [host, chart, s, {}];
  }

  // ------------------------------------------------------------ phone exchange / broker app screenshot
  function mobile() {
    const M = C.mobile;
    const accent = M.accent;
    root.style.cssText = `width:${C.w}px;height:${C.h}px;display:flex;flex-direction:column;background:${P.bg};font-family:${M.font};color:${P.fg}`;
    const sig = `<svg width="66" height="12" viewBox="0 0 66 12"><g fill="${P.fg}"><rect x="0" y="8" width="3" height="4" rx="1"/><rect x="5" y="6" width="3" height="6" rx="1"/><rect x="10" y="3" width="3" height="9" rx="1"/><rect x="15" y="0" width="3" height="12" rx="1"/><path d="M27 4a9 9 0 0112 0l-1.5 1.6a7 7 0 00-9 0zM30 7.2a4.6 4.6 0 016 0L33 10.5z"/><rect x="44" y="1" width="19" height="10" rx="2.5" fill="none" stroke="${P.fg}" stroke-width="1"/><rect x="46" y="3" width="${Math.round(15 * M.battery)}" height="6" rx="1"/><rect x="64" y="4" width="1.5" height="4" rx=".7"/></g></svg>`;
    root.appendChild(el('div', 'height:44px;display:flex;align-items:center;justify-content:space-between;padding:0 22px 0 28px;font-weight:600;font-size:15px', `<span>${M.clock}</span>${sig}`));
    root.appendChild(el('div', 'height:44px;display:flex;align-items:center;gap:10px;padding:0 14px;font-size:17px',
      `<span style="font-size:26px;font-weight:300;margin-top:-4px">‹</span><span style="font-weight:700">${M.pair}</span>${M.pair_sub ? `<span style="font-size:12px;color:${P.dim}">${M.pair_sub}</span>` : ''}<span style="flex:1"></span><span style="font-size:18px;color:${P.dim}">☆</span>`));
    root.appendChild(el('div', `display:flex;gap:18px;padding:2px 16px 8px;font-size:14px;color:${P.dim};border-bottom:1px solid ${P.border}`,
      M.tabs.map((t, i) => `<span style="${i === 0 ? `color:${P.fg};font-weight:600;border-bottom:2px solid ${accent};padding-bottom:6px` : ''}">${t}</span>`).join('')));
    const last = C.candles[C.candles.length - 1], prev = C.candles[C.candles.length - 2] || last;
    const ref = M.ref_close || prev.close;
    const pct = (last.close / ref - 1) * 100;
    const col = pct >= 0 ? P.up : P.down;
    const stats = M.stats.map(([k, v]) => `<div style="display:flex;justify-content:space-between;gap:8px"><span style="color:${P.dim}">${k}</span><span>${v}</span></div>`).join('');
    root.appendChild(el('div', 'display:flex;padding:12px 16px 6px;gap:14px',
      `<div style="flex:1.2"><div style="font-size:30px;font-weight:700;color:${col};letter-spacing:-.5px">${fmt(last.close, C.precision)}</div><div style="font-size:13px;margin-top:2px"><span>${M.fiat_prefix}${fmt(last.close, C.precision)}</span> <span style="color:${col};margin-left:6px">${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%</span></div>${M.tag ? `<div style="display:inline-block;margin-top:6px;font-size:11px;color:${accent};background:${accent}22;padding:1px 6px;border-radius:3px">${M.tag}</div>` : ''}</div><div style="flex:1;font-size:11.5px;line-height:1.75">${stats}</div>`));
    root.appendChild(el('div', `display:flex;gap:16px;align-items:center;padding:8px 16px;font-size:13.5px;color:${P.dim};border-top:1px solid ${P.border}`,
      M.intervals.map((t) => `<span style="${t === M.active ? `color:${P.fg};font-weight:600;${M.active_bg ? `background:${P.hover};padding:2px 8px;border-radius:4px` : `border-bottom:2px solid ${accent};padding-bottom:3px`}` : ''}">${t}</span>`).join('') + `<span style="flex:1"></span>${icon('<path d="M6 20l5-7 4 4 7-10"/>', 20)}`));
    if (C.ma && C.ma.length) {
      root.appendChild(el('div', 'padding:2px 12px;font-size:11px;display:flex;gap:10px;flex-wrap:wrap',
        C.ma.map((m) => `<span style="color:${m.color}">${m.name}: ${fmt(m.data[m.data.length - 1].value, C.precision)}</span>`).join('')));
    }
    const host = el('div', 'flex:1;position:relative;min-height:0');
    root.appendChild(host);
    const chart = makeChart(host, { volume: true, fontSize: 10, barSpacing: C.bar_spacing, timeVisible: C.intraday,
      rightOffset: 3, font: M.font, vgrid: false });
    const s = candles(chart, { volume: true, ma: C.ma, up: P.up, down: P.down });
    chart.timeScale().scrollToRealTime();
    if (M.buttons) {
      root.appendChild(el('div', `display:flex;gap:10px;padding:10px 14px 26px;border-top:1px solid ${P.border}`,
        `<div style="flex:1;text-align:center;padding:11px 0;border-radius:6px;background:${P.up};color:#fff;font-weight:600;font-size:15px">${M.buttons[0]}</div><div style="flex:1;text-align:center;padding:11px 0;border-radius:6px;background:${P.down};color:#fff;font-weight:600;font-size:15px">${M.buttons[1]}</div>`));
    }
    return [host, chart, s, { labelSize: 10, font: M.font }];
  }

  // ------------------------------------------------------------ data panel (on-chain / research / macro export)
  function panel() {
    const font = C.panel.font;
    root.style.cssText = `width:${C.w}px;height:${C.h}px;display:flex;flex-direction:column;background:${P.bg};font-family:${font};color:${P.fg};padding:${C.panel.pad}px;box-sizing:border-box`;
    root.appendChild(el('div', `font-size:${C.panel.title_size}px;font-weight:700;letter-spacing:-.2px`, C.panel.title));
    if (C.panel.subtitle) root.appendChild(el('div', `font-size:13px;color:${P.dim};margin-top:3px`, C.panel.subtitle));
    root.appendChild(el('div', 'display:flex;gap:16px;font-size:12.5px;margin:10px 0 4px',
      C.series.map((s) => `<span style="display:flex;align-items:center;gap:6px"><span style="width:14px;height:${s.type === 'area' ? 8 : 2}px;background:${s.color};display:inline-block"></span>${s.name}</span>`).join('')));
    const host = el('div', 'flex:1;position:relative;min-height:0');
    root.appendChild(host);
    if (C.panel.footer) root.appendChild(el('div', `font-size:11px;color:${P.dim};margin-top:6px;display:flex;justify-content:space-between`, C.panel.footer));
    const f0 = C.series[0].format;
    const chart = makeChart(host, { left: C.series.some((s) => s.scale === 'left'), font, fontSize: 11.5, timeBorder: true,
      priceFormatter: f0 === 'percent' ? (v) => v.toFixed(2) + '%' : f0 === 'big' ? (v) => '$' + big(v) : (v) => fmt(v, C.series[0].precision || 0),
      barSpacing: Math.max(0.5, (C.w - 120) / Math.max(C.series[0].data.length, 1)), vgrid: C.panel.vgrid,
      extra: { rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.08, bottom: 0.06 } } } });
    let first = null;
    C.series.forEach((s) => {
      const opts = { color: s.color, lineWidth: s.width || 2, priceScaleId: s.scale || 'right', priceLineVisible: false,
        lastValueVisible: s.last !== false, crosshairMarkerVisible: false,
        priceFormat: s.format === 'percent' ? { type: 'custom', formatter: (v) => v.toFixed(2) + '%' }
          : s.format === 'big' ? { type: 'custom', formatter: (v) => '$' + big(v) } : { type: 'price', precision: s.precision || 0, minMove: Math.pow(10, -(s.precision || 0)) } };
      const ser = s.type === 'area' ? chart.addAreaSeries(Object.assign(opts, { lineColor: s.color, topColor: s.color + '55', bottomColor: s.color + '05' }))
        : chart.addLineSeries(opts);
      ser.setData(s.data);
      if (!first) first = ser;
    });
    chart.timeScale().fitContent();
    return [host, chart, first, { font }];
  }

  // ------------------------------------------------------------ perp funding / open-interest table
  function table() {
    const T = C.table;
    root.style.cssText = `width:${C.w}px;background:${P.bg};font-family:${T.font};color:${P.fg};padding:18px 20px 14px;box-sizing:border-box`;
    root.appendChild(el('div', 'font-size:18px;font-weight:700', T.title));
    if (T.subtitle) root.appendChild(el('div', `font-size:12.5px;color:${P.dim};margin:3px 0 10px`, T.subtitle));
    const head = T.columns.map((c, i) => `<th style="text-align:${i ? 'right' : 'left'};font-weight:500;color:${P.dim};padding:9px 10px;border-bottom:1px solid ${P.border}">${c}</th>`).join('');
    const rows = T.rows.map((r) => `<tr style="${r.hl ? `background:${P.hover}` : ''}">` + r.cells.map((c, i) => {
      const color = c.sign === undefined ? P.fg : c.sign > 0 ? P.up : c.sign < 0 ? P.down : P.fg;
      return `<td style="text-align:${i ? 'right' : 'left'};padding:9px 10px;border-bottom:1px solid ${P.border};color:${color};${i ? 'font-variant-numeric:tabular-nums' : 'font-weight:600'}">${c.v}</td>`;
    }).join('') + '</tr>').join('');
    root.appendChild(el('table', 'border-collapse:collapse;width:100%;font-size:14px', `<thead><tr>${head}</tr></thead><tbody>${rows}</tbody>`));
    if (T.footer) root.appendChild(el('div', `font-size:11px;color:${P.dim};margin-top:10px`, T.footer));
    return null;
  }

  const made = { tv, mobile, panel, table }[C.style]();
  requestAnimationFrame(() => requestAnimationFrame(() => {
    if (made) drawLevels(made[0], made[1], made[2], made[3]);
    info.height = root.getBoundingClientRect().height;
    window.__ready = true;
  }));
})();
