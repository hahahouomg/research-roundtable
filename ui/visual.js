/*!
 * 经纬 · Warp & Weft — visual.js
 *
 * A warp-weighted loom for multi-agent discussions.
 *   warp  (vertical band, fixed colour)  = one participant
 *   weft  (horizontal row)               = one recorded phase, in recorded order
 *   weave (texture of a row)             = phase kind
 *   marks (knots, snapped ends, pegs…)   = the seat state that was recorded
 *
 * Contract
 *   window.createDiscussionVisual(model) -> HTML string. Pure apart from a small
 *     per-discussion memory (which thread is pulled, which rows/cells just
 *     appeared) so the same markup can be reproduced on every host patch.
 *   window.syncDiscussionVisual(root, model) -> binds one delegated listener set
 *     per root (pull a thread, drag a loom weight, Esc, click a cell).
 *
 * No network, no inline style attributes, no inline handlers. Every interpolated
 * string goes through esc().
 */
(function () {
  'use strict';

  var KINDS = ['proposal', 'review', 'draft', 'ballot', 'document', 'execution', 'other'];
  var STATES = ['absent', 'pending', 'writing', 'permission', 'done', 'error', 'unfinished', 'accept', 'object', 'invalid'];
  var WOVEN = { done: 1, accept: 1, object: 1, invalid: 1 };
  var VOTED = { accept: 1, object: 1, invalid: 1 };
  var OFF_LOOM = { consensus: 1, disputed: 1, closed: 1, implementing: 1, returned: 1, inspect: 1 };
  var NEW_MS = 1600;   // a row counts as "just woven in" for this long after first sight
  var BEAT_MS = 1300;  // a cell that just turned woven keeps its beat-in class this long
  var MAX_BANDS = 6;

  /* ------------------------------------------------------------------ copy */

  var T = {
    zh: {
      lang: 'zh-CN',
      topic: '议题',
      meta: function (n, r) { return n + ' 位参与者 · ' + r + ' 个阶段'; },
      warp: '经线', warpSub: '一位一束',
      fell: '织口', fellLive: '正在织', halt: '停机', hem: '收边',
      unwoven: '未织', unwovenSub: '拉线坠', fringe: '流苏', fringeSub: '拉一根线',
      live: '现场', backLive: '回到现场', stopping: '正在停机…',
      status: {
        active: '织造中', summarizing: '收束成文', consensus: '一致', disputed: '有分歧', closed: '已结束',
        stopped: '已停止', incomplete: '未完成', implementing: '实施中', returned: '实施已返回', inspect: '实施中断'
      },
      line: {
        active: '讨论目前没有在运行。',
        summarizing: '正在收束成文。',
        consensus: '讨论以“一致”结束。',
        disputed: '讨论结束，但留有分歧。',
        closed: '讨论已结束。',
        stopped: '织机被停下了：讨论在中途停止。',
        incomplete: '这块布没有织完。',
        implementing: '讨论已进入实施。',
        returned: '实施结果已经返回，可以查看报告。',
        inspect: '实施中断，已收到的报告可以查看。'
      },
      state: {
        absent: '无记录', pending: '已开始，尚无文字', writing: '正在写', permission: '等你许可', done: '已完成',
        error: '出错', unfinished: '未完成', accept: '赞成', object: '反对', invalid: '无效票'
      },
      noVote: '未投票',
      carried: '沿用早先的票',
      kind: { proposal: '提案', review: '互评', draft: '修订', ballot: '表决', document: '定稿', execution: '实施', other: '其他' },
      weave: { proposal: '平纹', review: '斜纹', draft: '缎纹', ballot: '纱罗结', document: '织锦', execution: '绗线', other: '方平' },
      round: function (i) { return '阶段 ' + i; },
      tally: function (d, n) { return d + '/' + n + ' 完成'; },
      votes: function (a, o) { return a + ' 赞成 · ' + o + ' 反对'; },
      read: '原文',
      readAria: function (who, what) { return '在阅读器中打开 ' + who + ' 在「' + what + '」的原文'; },
      readDoc: '读定稿',
      req: '去查看并确认',
      reqAria: function (who, what) { return who + ' 请求许可：' + what + '。去查看并确认'; },
      hold: '许可',
      nowWait: function (who, what, more) { return who + ' 在等你许可：' + what + (more ? '（另有 ' + more + ' 项）' : ''); },
      nowWriting: function (who, what) { return who + ' 正在写「' + what + '」'; },
      nowPending: function (who, what) { return who + ' 已开始「' + what + '」，还没有文字'; },
      nowLatest: function (what) { return '最近一轮是「' + what + '」，织机仍在运转'; },
      nowStart: '织机在运转，还没有任何记录',
      and: function (a) { return a.join('、'); },
      pullAria: function (who) { return who + ' 的线：抽出来，按时间读它每一轮的原话'; },
      calls: function (n) { return n + ' 段发言'; },
      back: '织回去',
      clothAria: '讨论之布：每一行是一轮',
      final: '成布',
      noDoc: '没有记录到定稿文档',
      ballot: '最后一次表决',
      empty: '经线已经挂好，还没有任何一轮。',
      notHere: '这一轮没有它的记录',
      keyTitle: '怎么读这块布',
      key1: '每位参与者是一束固定颜色的竖向经线；每一横行是一轮，按记录顺序从上往下织。',
      key2: '点一行，读这一轮每位的原话；点线轴，或把下方的线坠往下拉，就把这一位的线抽出来，按时间读它说过的话。Esc 织回。',
      keyKinds: '纹样 = 这一轮在做什么',
      keyMarks: '记号 = 记录到的状态',
      mark: { accept: '赞成', object: '反对', carried: '沿用早先的票', error: '出错', unfinished: '未完成', permission: '等你许可', absent: '无记录' },
      cardAria: '所选的一轮',
      latest: '最新'
    },
    en: {
      lang: 'en',
      topic: 'Topic',
      meta: function (n, r) { return n + ' seats · ' + r + (r === 1 ? ' stage' : ' stages'); },
      warp: 'Warp', warpSub: 'one band each',
      fell: 'Fell', fellLive: 'weaving now', halt: 'stopped', hem: 'Hem',
      unwoven: 'Unwoven', unwovenSub: 'drag a weight', fringe: 'Fringe', fringeSub: 'pull a thread',
      live: 'Live', backLive: 'Back to live', stopping: 'Stopping…',
      status: {
        active: 'Weaving', summarizing: 'Writing up', consensus: 'Consensus', disputed: 'Disputed', closed: 'Closed',
        stopped: 'Stopped', incomplete: 'Incomplete', implementing: 'Implementing', returned: 'Implementation returned', inspect: 'Implementation interrupted'
      },
      line: {
        active: 'Not running right now.',
        summarizing: 'Writing it up.',
        consensus: 'Finished in consensus.',
        disputed: 'Finished, with dissent on record.',
        closed: 'This discussion is closed.',
        stopped: 'The loom was stopped partway through.',
        incomplete: 'This cloth was left unfinished.',
        implementing: 'The discussion has moved into implementation.',
        returned: 'The implementation report is available.',
        inspect: 'Implementation was interrupted.'
      },
      state: {
        absent: 'No call', pending: 'Started · no text yet', writing: 'Writing', permission: 'Needs your permission', done: 'Done',
        error: 'Error', unfinished: 'Unfinished', accept: 'Accept', object: 'Object', invalid: 'Invalid ballot'
      },
      noVote: 'No vote',
      carried: 'earlier vote kept',
      kind: { proposal: 'Proposal', review: 'Review', draft: 'Revision', ballot: 'Ballot', document: 'Document', execution: 'Execution', other: 'Other' },
      weave: { proposal: 'Plain weave', review: 'Twill', draft: 'Satin', ballot: 'Gauze knots', document: 'Brocade', execution: 'Running stitch', other: 'Basket weave' },
      round: function (i) { return 'Stage ' + i; },
      tally: function (d, n) { return d + '/' + n + ' done'; },
      votes: function (a, o) { return a + ' accept · ' + o + ' object'; },
      read: 'Original',
      readAria: function (who, what) { return 'Open ' + who + '’s original text for “' + what + '” in the reader'; },
      readDoc: 'Read the final',
      req: 'Review request',
      reqAria: function (who, what) { return who + ' asks for permission: ' + what + '. Review request'; },
      hold: 'Permission',
      nowWait: function (who, what, more) { return who + ' is waiting for your permission: ' + what + (more ? ' (+' + more + ' more)' : ''); },
      nowWriting: function (who, what, n) { return who + (n > 1 ? ' are' : ' is') + ' writing “' + what + '”'; },
      nowPending: function (who, what) { return who + ' started “' + what + '” — no text yet'; },
      nowLatest: function (what) { return 'Latest round: “' + what + '”. The loom is still running'; },
      nowStart: 'The loom is running; nothing recorded yet',
      and: function (a) { return a.length < 2 ? a.join('') : a.slice(0, -1).join(', ') + ' and ' + a[a.length - 1]; },
      pullAria: function (who) { return who + '’s thread — pull it out to read every round in order'; },
      calls: function (n) { return n + (n === 1 ? ' turn' : ' turns'); },
      back: 'Weave back',
      clothAria: 'The discussion cloth: one row per round',
      final: 'Off the loom',
      noDoc: 'No final document was recorded',
      ballot: 'Latest ballot',
      empty: 'The warp is hung; no round has started yet.',
      notHere: 'Nothing recorded for this seat in this round',
      keyTitle: 'How to read the cloth',
      key1: 'Each participant is one band of warp in a fixed colour. Each row is one round, woven top to bottom in recorded order.',
      key2: 'Click a row to read that round word for word. Click a spool, or drag a loom weight down, to pull one participant’s thread out and read it in order. Esc weaves it back.',
      keyKinds: 'Weave = what the round was',
      keyMarks: 'Marks = what was recorded',
      mark: { accept: 'Accept', object: 'Object', carried: 'Earlier vote kept', error: 'Error', unfinished: 'Unfinished', permission: 'Needs permission', absent: 'No call' },
      cardAria: 'Selected round',
      latest: 'now'
    }
  };

  /* ------------------------------------------------------------ artwork */
  /* Hand-drawn inline SVG; colours come from CSS (var(--c) per band).     */

  var A = ' aria-hidden="true" focusable="false"';
  var ARROW = '<svg class="lw-ico" viewBox="0 0 16 16"' + A + '><path d="M3 8h9M8.5 4.5 12 8l-3.5 3.5"/></svg>';
  var DOC = '<svg class="lw-ico lw-ico--doc" viewBox="0 0 24 24"' + A + '><path d="M6 3h9l3 3v15H6zM15 3v3h3M9 11h6M9 15h6"/></svg>';
  var DOWN = '<svg class="lw-ico" viewBox="0 0 16 16"' + A + '><path d="M8 2.5v8M4.5 7 8 10.5 11.5 7M3 13.5h10"/></svg>';
  var PEG = '<svg class="lw-peg" viewBox="0 0 24 24"' + A + '><circle cx="12" cy="12" r="9"/><path d="M9.5 8v8M14.5 8v8"/></svg>';
  var SHUTTLE = '<svg class="lw-shuttle" viewBox="0 0 56 18"' + A + '>' +
    '<path class="lw-sh-wood" d="M1 9C9 1.5 47 1.5 55 9 47 16.5 9 16.5 1 9Z"/>' +
    '<path class="lw-sh-cut" d="M17 6.2h22v5.6H17Z"/>' +
    '<rect class="lw-g-fill" x="19" y="7.2" width="18" height="3.6" rx="1.8"/>' +
    '<path class="lw-sh-grain" d="M6 9h8M42 9h8"/></svg>';
  var YARN = '<svg class="lw-yarn" viewBox="0 0 24 100" preserveAspectRatio="none"' + A + '>' +
    '<path d="M12 0C20 20 4 30 12 50S4 80 12 100" vector-effect="non-scaling-stroke"/></svg>';
  var SNAP = '<svg class="lw-snap" viewBox="0 0 32 40"' + A + '>' +
    '<path class="lw-g-break" d="M16 0v12c0 4-5 5-6 1"/><path class="lw-g-break" d="M16 40V28c0-4 5-5 6-1"/>' +
    '<path class="lw-g-spark" d="M12 18l-3-2M20 22l3 2M16 17v-2.5M16 23v2.5"/></svg>';
  var FRAY = '<svg class="lw-fray" viewBox="0 0 48 18"' + A + '>' +
    '<path class="lw-g-break" d="M6 0q2 8-1 15M15 0q-2 6 1 11M24 0q2 9 0 17M33 0q-2 7 1 12M42 0q2 6-1 13"/></svg>';
  var STONE = '<svg class="lw-stone" viewBox="0 0 36 44"' + A + '>' +
    '<path class="lw-st-body" d="M11 2h14l8.5 37.5Q18 44 2.5 39.5Z"/>' +
    '<circle class="lw-st-hole" cx="18" cy="10" r="3.2"/>' +
    '<path class="lw-g-fill" d="M7.2 24h21.6l1.3 6H5.9Z"/>' +
    '<path class="lw-st-hi" d="M12.5 5 6 37"/></svg>';
  var TASSEL = '<svg class="lw-tassel" viewBox="0 0 36 52"' + A + '>' +
    '<path class="lw-ta-str" d="M14 16C12 28 9 38 7 50M16 17c-1 12-2 22-3 34M18 17v35M20 17c1 12 2 22 3 34M22 16c2 12 5 22 7 34"/>' +
    '<path class="lw-ta-cord" d="M18 0v9"/>' +
    '<circle class="lw-g-fill lw-g-edge" cx="18" cy="12.5" r="5"/></svg>';
  var SPOOL = (function () {
    var w = '';
    for (var y = -8; y <= 44; y += 4) w += 'M0 ' + y + 'L26 ' + (y + 3);
    return '<svg class="lw-spool-svg" viewBox="0 0 40 52"' + A + '>' +
      '<rect class="lw-wood" x="2" y="1" width="36" height="7" rx="3.5"/>' +
      '<svg x="7" y="8" width="26" height="36" viewBox="0 0 26 36">' +
        '<rect class="lw-g-fill" width="26" height="36"/>' +
        '<path class="lw-wind" d="' + w + '"/>' +
        '<rect class="lw-yarn-hi" x="3" width="6" height="36"/>' +
        '<rect class="lw-yarn-lo" x="19" width="7" height="36"/>' +
      '</svg>' +
      '<rect class="lw-wood" x="2" y="44" width="36" height="7" rx="3.5"/></svg>';
  })();
  var CONV = (function () {
    var d = '';
    for (var j = 0; j < 9; j++) d += 'M' + (6 + j * 11) + ' 0L50 52';
    return '<svg class="lw-conv" viewBox="0 0 100 52" preserveAspectRatio="none"' + A + '>' +
      '<path d="' + d + '" vector-effect="non-scaling-stroke"/></svg>';
  })();
  function fanSvg(n) {
    var p = '';
    for (var k = 0; k < n; k++) {
      var d = '';
      for (var j = 0; j < 9; j++) d += 'M' + (k * 100 + 50) + ' 0L' + (k * 100 + 6 + j * 11) + ' 34';
      p += '<path class="lw-b' + (k % MAX_BANDS) + '" d="' + d + '" vector-effect="non-scaling-stroke"/>';
    }
    return '<svg class="lw-fan-svg" viewBox="0 0 ' + Math.max(n, 1) * 100 + ' 34" preserveAspectRatio="none"' + A + '>' + p + '</svg>';
  }

  var KNOT = {
    accept: '<svg class="lw-knot lw-knot--ok" viewBox="0 0 32 32"' + A + '>' +
      '<path class="lw-g-tail" d="M1 16h8M23 16h8"/>' +
      '<circle class="lw-g-fill lw-g-edge" cx="16" cy="16" r="7.5"/>' +
      '<path class="lw-g-hi" d="M11.8 13.6c2.4-2.8 6-2.8 8.4 0M11.8 18.4c2.4 2.8 6 2.8 8.4 0"/></svg>',
    object: '<svg class="lw-knot lw-knot--no" viewBox="0 0 32 32"' + A + '>' +
      '<path class="lw-g-tail" d="M1 16h7M24 16h7"/>' +
      '<path class="lw-g-fill lw-g-edge" d="M16 4.5l2.6 6.3 6.6-1.6-3.5 5.8 5.3 3.9-6.7.8-.4 6.8L16 21.6l-3.9 4.9-.4-6.8-6.7-.8 5.3-3.9-3.5-5.8 6.6 1.6z"/>' +
      '<path class="lw-g-x" d="M13.4 13.4l5.2 5.2M18.6 13.4l-5.2 5.2"/></svg>',
    invalid: '<svg class="lw-knot lw-knot--void" viewBox="0 0 32 32"' + A + '>' +
      '<path class="lw-g-tail" d="M1 16h8M23 16h8"/>' +
      '<circle class="lw-g-dash" cx="16" cy="16" r="7"/><path class="lw-g-break" d="M11.5 20.5l9-9"/></svg>',
    none: '<svg class="lw-knot lw-knot--none" viewBox="0 0 32 32"' + A + '><circle class="lw-g-dash" cx="16" cy="16" r="4.5"/></svg>'
  };
  var RET = '<circle class="lw-g-ret" cx="16" cy="16" r="12.5"/>';
  var BEAD = {
    done: '<svg class="lw-dot" viewBox="0 0 24 24"' + A + '><circle class="lw-g-fill lw-g-edge" cx="12" cy="12" r="6.5"/><circle class="lw-g-shine" cx="9.8" cy="9.6" r="2"/></svg>',
    writing: '<svg class="lw-dot lw-dot--live" viewBox="0 0 24 24"' + A + '><circle class="lw-g-ring" cx="12" cy="12" r="7.5"/><circle class="lw-g-fill" cx="12" cy="12" r="3.4"/></svg>',
    pending: '<svg class="lw-dot" viewBox="0 0 24 24"' + A + '><circle class="lw-g-dash" cx="12" cy="12" r="6.5"/></svg>',
    permission: PEG,
    error: '<svg class="lw-dot" viewBox="0 0 24 24"' + A + '><path class="lw-g-spark" d="M7.5 7.5l9 9M16.5 7.5l-9 9"/></svg>',
    unfinished: '<svg class="lw-dot" viewBox="0 0 24 24"' + A + '><circle class="lw-g-dash" cx="12" cy="12" r="6.5"/><path class="lw-g-fill" d="M5.5 12a6.5 6.5 0 0 1 13 0z"/></svg>',
    absent: '<svg class="lw-dot lw-dot--none" viewBox="0 0 24 24"' + A + '><circle class="lw-g-dash" cx="12" cy="12" r="4"/></svg>'
  };

  function knot(state, carried) {
    var s = KNOT[state] || KNOT.none;
    return carried ? s.replace('</svg>', RET + '</svg>') : s;
  }
  /* glyph drawn on the cloth itself */
  function markSvg(kind, s) {
    if (VOTED[s.state]) return knot(s.state, s.carried);
    if (kind === 'ballot' && s.state === 'absent') return KNOT.none;
    if (s.state === 'error') return SNAP;
    if (s.state === 'unfinished') return FRAY;
    return '';
  }
  /* bead on a pulled thread, and the small seat glyph in cards */
  function beadSvg(kind, s) {
    if (VOTED[s.state]) return knot(s.state, s.carried);
    if (kind === 'ballot' && s.state === 'absent') return KNOT.none;
    return BEAD[s.state] || BEAD.done;
  }

  /* ------------------------------------------------------------ helpers */

  function str(v) { return v == null ? '' : String(v); }
  function esc(v) {
    return str(v).replace(/[&<>"']/g, function (ch) {
      return ch === '&' ? '&amp;' : ch === '<' ? '&lt;' : ch === '>' ? '&gt;' : ch === '"' ? '&quot;' : '&#39;';
    });
  }
  function clip(v, n) {
    var a = Array.from(str(v).replace(/\s+/g, ' ').trim());
    return a.length > n ? a.slice(0, n).join('') + '…' : a.join('');
  }
  function pad2(n) { return n < 10 ? '0' + n : String(n); }
  function toInt(v, d) {
    var n = typeof v === 'number' ? v : parseInt(v, 10);
    return isFinite(n) ? Math.floor(n) : d;
  }
  function statusKey(s) {
    s = str(s).toLowerCase();
    return /^[a-z]{1,24}$/.test(s) ? s : 'active';
  }

  var store = Object.create(null);
  function mem(id) {
    return store[id] || (store[id] = {
      pull: null, pullIdx: -1, ids: [], focus: null, base: 'lw',
      seen: new Map(), prev: new Map(), beat: new Map()
    });
  }
  function pullCls(m) {
    return m.pullIdx >= 0 && m.pullIdx < MAX_BANDS ? ' lw--pull lw--pull-' + m.pullIdx : '';
  }

  function agentsOf(model) {
    var out = [], seen = Object.create(null);
    function add(a) {
      if (!a || a.id == null) return;
      var id = String(a.id);
      if (seen[id]) return;
      seen[id] = 1;
      out.push({ id: id, name: str(a.name) || id });
    }
    (Array.isArray(model.agents) ? model.agents : []).forEach(add);
    if (!out.length) {
      (Array.isArray(model.phases) ? model.phases : []).forEach(function (p) {
        (p && Array.isArray(p.seats) ? p.seats : []).forEach(add);
      });
    }
    return out;
  }
  function nameOf(agents, id) {
    for (var i = 0; i < agents.length; i++) if (agents[i].id === String(id)) return agents[i].name;
    return str(id);
  }

  function seatOf(phase, kind, agent) {
    var list = Array.isArray(phase.seats) ? phase.seats : [];
    var s = null;
    for (var i = 0; i < list.length; i++) {
      if (list[i] && String(list[i].id) === agent.id) { s = list[i]; break; }
    }
    var callId = s && s.callId != null && s.callId !== '' ? String(s.callId) : null;
    var state = s && STATES.indexOf(s.state) >= 0 ? s.state : (callId ? 'done' : 'absent');
    var vote = s && (s.vote === 'accept' || s.vote === 'object') ? s.vote : null;
    if (kind === 'ballot' && vote && (state === 'done' || state === 'accept' || state === 'object')) state = vote;
    return {
      state: state,
      vote: vote,
      callId: callId,
      carried: !!(s && s.carried),
      excerpt: s ? str(s.excerpt) : '',
      reason: s ? str(s.reason) : '',
      requestId: s && s.requestId != null && s.requestId !== '' ? String(s.requestId) : null,
      requestTitle: s ? str(s.requestTitle) : ''
    };
  }

  function derive(model, agents, t) {
    var phases = Array.isArray(model.phases) ? model.phases : [];
    return phases.map(function (p, i) {
      p = p || {};
      var kind = KINDS.indexOf(p.kind) >= 0 ? p.kind : 'other';
      return {
        i: i,
        kind: kind,
        name: str(p.name),
        title: str(p.title) || str(p.name) || t.round(i + 1),
        seats: agents.map(function (a, k) {
          var s = seatOf(p, kind, a);
          s.agent = a;
          s.k = k % MAX_BANDS;
          return s;
        })
      };
    });
  }

  function stateLabel(t, kind, s) {
    if (kind === 'ballot' && s.state === 'absent') return t.noVote;
    return t.state[s.state] || t.state.done;
  }

  function summary(row, t) {
    var c = {};
    row.seats.forEach(function (s) { c[s.state] = (c[s.state] || 0) + 1; });
    if (row.kind === 'ballot' && (c.accept || c.object)) return t.votes(c.accept || 0, c.object || 0);
    if (c.permission) return t.state.permission;
    if (c.writing) return t.state.writing;
    var d = (c.done || 0) + (c.accept || 0) + (c.object || 0) + (c.invalid || 0);
    return t.tally(d, row.seats.length - (c.absent || 0));
  }

  function nowLine(c) {
    var t = c.t, model = c.model;
    var reqs = Array.isArray(model.requests) ? model.requests : [];
    if (reqs.length) {
      var r = reqs[0] || {};
      return t.nowWait(esc(nameOf(c.agents, r.agent)), esc(r.title), reqs.length - 1);
    }
    if (model.stopping) return t.stopping;
    if (!c.running) return t.line[c.status] || '';
    if (!c.rows.length) return t.nowStart;
    var row = c.rows[c.latest];
    var w = [], p = [];
    row.seats.forEach(function (s) {
      if (s.state === 'writing') w.push(esc(s.agent.name));
      else if (s.state === 'pending') p.push(esc(s.agent.name));
    });
    if (w.length) return t.nowWriting(t.and(w), esc(row.title), w.length);
    if (p.length) return t.nowPending(t.and(p), esc(row.title), p.length);
    return t.nowLatest(esc(row.title));
  }

  function statusLabel(c) {
    return c.t.status[c.status] || esc(c.model.status);
  }

  /* -------------------------------------------------------------- parts */

  function readBtn(c, s, row) {
    /* only offer the original when a call exists and something was written */
    if (s.callId == null || s.state === 'absent' || (s.state === 'pending' && !s.excerpt)) return '';
    return '<button type="button" class="lw-read" data-read="call-' + esc(s.callId) + '" aria-label="' +
      c.t.readAria(esc(s.agent.name), esc(row.title)) + '">' + c.t.read + ARROW + '</button>';
  }

  function reqBtn(c, s) {
    if (s.requestId == null) return '';
    return '<button type="button" class="lw-reqmini" data-visual-request="' + esc(s.requestId) + '" aria-label="' +
      c.t.reqAria(esc(s.agent.name), esc(s.requestTitle || c.t.state.permission)) + '">' + PEG +
      '<span>' + (s.requestTitle ? esc(s.requestTitle) : c.t.req) + '</span>' + ARROW + '</button>';
  }

  function head(c) {
    var t = c.t, model = c.model;
    var topic = str(model.topic);
    var chip = '';
    if (model.stopping) {
      chip = '<span class="lw-chip lw-chip--stop">' + t.stopping + '</span>';
    } else if (c.running && model.following !== false) {
      chip = '<span class="lw-chip lw-chip--live"><i aria-hidden="true"></i>' + t.live + '</span>';
    } else if (c.running) {
      chip = '<button type="button" class="lw-chip lw-chip--back" data-visual-live>' + DOWN + t.backLive + '</button>';
    }
    var reqs = (Array.isArray(model.requests) ? model.requests : []).map(function (r) {
      r = r || {};
      var k = c.ids.indexOf(String(r.agent));
      var who = esc(nameOf(c.agents, r.agent));
      var what = esc(r.title);
      return '<li data-key="req-' + esc(r.id) + '"><button type="button" class="lw-req' + (k >= 0 ? ' lw-b' + (k % MAX_BANDS) : '') +
        '" data-visual-request="' + esc(r.id) + '" aria-label="' + t.reqAria(who, what) + '">' + PEG +
        '<span class="lw-req-who">' + who + '</span><span class="lw-req-what">' + what + '</span>' +
        '<span class="lw-req-go">' + t.req + ARROW + '</span></button></li>';
    }).join('');
    return '<header class="lw-head">' +
      '<div class="lw-label"><span class="lw-eyebrow">' + t.topic + ' · ' + t.meta(c.N, c.rows.length) + '</span>' +
        '<h1 class="lw-topic"' + (topic ? ' title="' + esc(topic) + '"' : '') + '>' + (esc(topic) || '—') + '</h1></div>' +
      '<div class="lw-state"><span class="lw-status lw-status--' + c.status + '"><i aria-hidden="true"></i>' + statusLabel(c) + '</span>' + chip + '</div>' +
      '<p class="lw-now" aria-live="polite">' + (c.running ? SHUTTLE : '') + '<span>' + c.nowText + '</span></p>' +
      (reqs ? '<ul class="lw-reqs">' + reqs + '</ul>' : '') +
    '</header>';
  }

  function beam(c) {
    var t = c.t;
    return '<div class="lw-beam lw-grid" data-key="beam">' +
      '<span class="lw-lab"><b>' + t.warp + '</b><small>' + t.warpSub + '</small></span>' +
      c.agents.map(function (a, k) {
        return '<div class="lw-post lw-b' + (k % MAX_BANDS) + '" data-key="post-' + esc(a.id) + '">' +
          '<button type="button" class="lw-spool' + (c.busy[a.id] ? ' is-busy' : '') + '" data-lw-thread="' + esc(a.id) +
            '" aria-pressed="' + (c.m.pull === a.id) + '" aria-label="' + t.pullAria(esc(a.name)) + '">' +
            SPOOL +
            '<span class="lw-spool-name">' + esc(a.name) + '</span>' +
            '<span class="lw-spool-meta">' + t.calls(c.calls[a.id] || 0) + '</span>' +
            '<span class="lw-spool-back" aria-hidden="true">' + t.back + '</span>' +
          '</button></div>';
      }).join('') +
    '</div>';
  }

  function fan(c) {
    return '<div class="lw-fan lw-grid" data-key="fan" aria-hidden="true"><span></span>' + fanSvg(c.N) + '</div>';
  }

  function say(c, row, s, label) {
    var t = c.t;
    if (s.state === 'absent') {
      return '<div class="lw-say"><span class="lw-say-none">' + (row.kind === 'ballot' ? t.noVote : t.notHere) + '</span></div>';
    }
    var body = '';
    if (s.excerpt) body += '<q class="lw-q">' + esc(s.excerpt) + (s.state === 'writing' ? '<i class="lw-caret" aria-hidden="true"></i>' : '') + '</q>';
    if (s.reason) body += '<span class="lw-reason">' + esc(s.reason) + '</span>';
    if (s.state === 'permission') body += reqBtn(c, s);
    return '<div class="lw-say"><span class="lw-say-head"><span class="lw-say-ph">' + pad2(row.i + 1) + ' · ' + esc(row.title) + '</span>' +
      '<span class="lw-say-st">' + label + (s.carried ? ' · ' + t.carried : '') + '</span>' + readBtn(c, s, row) + '</span>' + body + '</div>';
  }

  function cellHtml(c, row, s) {
    var t = c.t, a = s.agent, st = s.state;
    var label = stateLabel(t, row.kind, s);
    var quote = s.reason || s.excerpt;
    var cls = 'lw-cell lw-b' + s.k + ' lw-s-' + st + (s.carried ? ' is-carried' : '') + (s.beat ? ' lw-beat' : '');
    var hold = '';
    if (st === 'permission') {
      hold = s.requestId != null
        ? '<button type="button" class="lw-hold" data-visual-request="' + esc(s.requestId) + '" aria-label="' +
          t.reqAria(esc(a.name), esc(s.requestTitle || t.state.permission)) + '">' + PEG + '<span>' + t.hold + '</span></button>'
        : '<span class="lw-hold lw-hold--static" aria-hidden="true">' + PEG + '</span>';
    }
    var run = st === 'writing' || st === 'pending'
      ? '<span class="lw-run" aria-hidden="true"><span class="lw-run-in">' + SHUTTLE + '</span></span>' : '';
    var tip = '<span class="lw-tip" aria-hidden="true"><span class="lw-tip-h"><b>' + esc(a.name) + '</b><em>' + label +
      (s.carried ? ' · ' + t.carried : '') + '</em></span>' +
      (quote ? '<span class="lw-tip-q">' + esc(clip(quote, 150)) + '</span>' : '') + '</span>';
    return '<div class="' + cls + '" data-key="' + esc(s.key) + '" data-lw-phase="' + row.i + '" data-lw-agent="' + esc(a.id) + '">' +
      '<span class="lw-tex" aria-hidden="true"></span>' +
      YARN +
      '<span class="lw-mark" aria-hidden="true">' + markSvg(row.kind, s) + '</span>' +
      '<span class="lw-bead" aria-hidden="true">' + beadSvg(row.kind, s) + '</span>' +
      run + hold + tip + say(c, row, s, label) +
    '</div>';
  }

  function rowHtml(c, row) {
    var t = c.t, i = row.i, sel = i === c.sel;
    var latest = c.running && i === c.latest;
    var dissent = row.kind === 'ballot' && row.seats.some(function (s) { return s.state === 'object'; });
    var sum = summary(row, t);
    var cls = 'lw-row lw-grid lw-k-' + row.kind + ' lw-r' + Math.min(i, 15) +
      (sel ? ' is-sel' : '') + (latest ? ' is-latest' : '') +
      (row.isNew ? ' lw-new lw-d' + row.delay : '') + (dissent ? ' lw-dissent' : '');
    return '<li class="' + cls + '" data-key="' + esc(row.key) + '">' +
      '<button type="button" class="lw-pick" data-visual-phase="' + i + '"' + (sel ? ' aria-current="true"' : '') +
        ' aria-label="' + t.round(i + 1) + ' · ' + esc(row.title) + ' · ' + t.kind[row.kind] + ' · ' + sum + '">' +
        '<span class="lw-no">' + pad2(i + 1) + '</span>' +
        '<span class="lw-ttl">' + esc(row.title) + '</span>' +
        '<span class="lw-sub">' + t.kind[row.kind] + ' · ' + sum + '</span>' +
        (latest ? '<span class="lw-now-tag">' + t.latest + '</span>' : '') +
      '</button>' +
      row.seats.map(function (s) { return cellHtml(c, row, s); }).join('') +
    '</li>';
  }

  function cloth(c) {
    var t = c.t, html = '';
    if (!c.rows.length) {
      html = '<li class="lw-row lw-grid lw-empty" data-key="empty"><span class="lw-lab"></span>' +
        c.agents.map(function (a, k) { return '<div class="lw-cell lw-b' + (k % MAX_BANDS) + ' lw-s-absent"></div>'; }).join('') +
        '<p class="lw-empty-msg">' + (c.running ? t.nowStart : t.empty) + '</p></li>';
    }
    c.rows.forEach(function (row) {
      html += rowHtml(c, row);
      if (row.i === c.sel) html += '<li class="lw-inline" data-key="inline-' + row.i + '">' + card(c, row, 'inline') + '</li>';
    });
    return '<ol class="lw-cloth" data-key="cloth" aria-label="' + t.clothAria + '">' + html + '</ol>';
  }

  function fell(c) {
    var t = c.t;
    var weaving = c.rows.some(function (r) { return r.seats.some(function (s) { return s.state === 'writing' || s.state === 'pending'; }); });
    var lab = c.off ? t.hem : t.fell;
    var sub = c.off ? statusLabel(c) : c.running ? t.fellLive : c.halt ? t.halt : '';
    return '<div class="lw-fell lw-grid' + (c.beat ? ' lw-slam' : '') + '" data-key="fell" aria-hidden="true">' +
      '<span class="lw-lab"><b>' + lab + '</b><small>' + sub + '</small></span>' +
      '<span class="lw-beater"><span class="lw-reed"></span>' +
        (c.running && !weaving ? '<span class="lw-park">' + SHUTTLE + '</span>' : '') +
        (c.halt ? '<span class="lw-tie"></span>' : '') +
      '</span></div>';
  }

  function hang(c) {
    var t = c.t;
    return '<div class="lw-hang lw-grid" data-key="hang">' +
      '<span class="lw-lab"><b>' + (c.off ? t.fringe : t.unwoven) + '</b><small>' + (c.off ? t.fringeSub : t.unwovenSub) + '</small></span>' +
      c.agents.map(function (a, k) {
        return '<div class="lw-strand lw-b' + (k % MAX_BANDS) + '" data-key="strand-' + esc(a.id) + '">' + CONV +
          '<button type="button" class="lw-weight" tabindex="-1" data-lw-thread="' + esc(a.id) + '" aria-pressed="' + (c.m.pull === a.id) +
            '" aria-label="' + t.pullAria(esc(a.name)) + '">' + STONE + TASSEL + '</button></div>';
      }).join('') +
    '</div>';
  }

  function card(c, row, where) {
    var t = c.t;
    var seats = row.seats.map(function (s) {
      var label = stateLabel(t, row.kind, s);
      var focus = !!c.m.focus && c.m.focus.i === row.i && c.m.focus.a === s.agent.id;
      var body = '';
      if (s.excerpt) body += '<q class="lw-q">' + esc(s.excerpt) + (s.state === 'writing' ? '<i class="lw-caret" aria-hidden="true"></i>' : '') + '</q>';
      if (s.reason) body += '<p class="lw-reason">' + esc(s.reason) + '</p>';
      if (s.state === 'permission') body += reqBtn(c, s);
      if (s.state === 'absent') body += '<p class="lw-none">' + (row.kind === 'ballot' ? t.noVote : t.notHere) + '</p>';
      return '<li class="lw-seat lw-b' + s.k + ' lw-s-' + s.state + (s.carried ? ' is-carried' : '') + (focus ? ' lw-seat--focus' : '') +
        '" data-key="seat-' + where + '-' + row.i + '-' + esc(s.agent.id) + '" data-lw-phase="' + row.i + '" data-lw-agent="' + esc(s.agent.id) + '">' +
        '<div class="lw-seat-head"><span class="lw-seat-knot" aria-hidden="true">' + beadSvg(row.kind, s) + '</span>' +
          '<b class="lw-seat-name">' + esc(s.agent.name) + '</b>' +
          '<span class="lw-seat-state">' + label + (s.carried ? ' · ' + t.carried : '') + '</span>' + readBtn(c, s, row) + '</div>' +
        body + '</li>';
    }).join('');
    return '<section class="lw-card lw-k-' + row.kind + '" data-key="card-' + where + '" aria-label="' + t.cardAria + '">' +
      '<div class="lw-card-head"><span class="lw-swatch" aria-hidden="true"><span class="lw-tex"></span></span>' +
        '<div class="lw-card-hd"><span class="lw-eyebrow">' + t.round(row.i + 1) + ' · ' + t.kind[row.kind] + ' · ' + t.weave[row.kind] + '</span>' +
        '<h3 class="lw-card-title">' + esc(row.title) + '</h3>' +
        '<span class="lw-card-sum">' + summary(row, t) + '</span></div></div>' +
      '<ol class="lw-seats">' + seats + '</ol></section>';
  }

  function verdict(c) {
    var t = c.t;
    var docs = (Array.isArray(c.model.documents) ? c.model.documents : []).filter(function (d) { return d && d.id != null && d.id !== ''; });
    if (!c.off && !docs.length) return '';
    var docHtml = docs.length
      ? '<div class="lw-docs">' + docs.map(function (d) {
          return '<button type="button" class="lw-doc" data-read="' + esc(d.id) + '" data-key="doc-' + esc(d.id) + '">' + DOC +
            '<span class="lw-doc-k">' + t.readDoc + '</span><b class="lw-doc-n">' + (esc(d.name) || esc(d.id)) + '</b>' + ARROW + '</button>';
        }).join('') + '</div>'
      : '<p class="lw-nodoc">' + t.noDoc + '</p>';
    var lb = null;
    for (var i = c.rows.length - 1; i >= 0; i--) if (c.rows[i].kind === 'ballot') { lb = c.rows[i]; break; }
    var tally = '';
    if (lb) {
      var acc = 0, obj = 0;
      lb.seats.forEach(function (s) { if (s.state === 'accept') acc++; else if (s.state === 'object') obj++; });
      tally = '<div class="lw-tally">' +
        '<div class="lw-tally-head"><span class="lw-eyebrow">' + t.ballot + '</span>' +
          '<button type="button" class="lw-tally-ph" data-visual-phase="' + lb.i + '">' + pad2(lb.i + 1) + ' · ' + esc(lb.title) + '</button>' +
          '<span class="lw-tally-sum">' + t.votes(acc, obj) + '</span></div>' +
        '<ul class="lw-votes">' + lb.seats.map(function (s) {
          return '<li class="lw-vote lw-b' + s.k + ' lw-s-' + s.state + (s.carried ? ' is-carried' : '') + '" data-key="vote-' + esc(s.agent.id) + '">' +
            '<span class="lw-vote-knot" aria-hidden="true">' + beadSvg('ballot', s) + '</span>' +
            '<b class="lw-vote-name">' + esc(s.agent.name) + '</b>' +
            '<span class="lw-vote-st">' + stateLabel(t, 'ballot', s) + (s.carried ? ' · ' + t.carried : '') + '</span>' +
            readBtn(c, s, lb) +
            (s.reason ? '<p class="lw-vote-why">' + esc(s.reason) + '</p>' : '') + '</li>';
        }).join('') + '</ul></div>';
    }
    return '<section class="lw-verdict lw-verdict--' + c.status + '" data-key="verdict">' +
      '<div class="lw-tag"><span class="lw-eyebrow">' + t.final + '</span>' +
        '<h3 class="lw-v-st">' + statusLabel(c) + '</h3>' +
        docHtml + '</div>' + tally + '</section>';
  }

  function legend(c) {
    var t = c.t, present = {};
    c.rows.forEach(function (r) { present[r.kind] = 1; });
    var kinds = KINDS.filter(function (k) { return present[k]; });
    if (!kinds.length) kinds = ['proposal', 'review', 'draft', 'ballot', 'document'];
    var sw = kinds.map(function (k) {
      return '<li class="lw-k-' + k + '"><span class="lw-swatch" aria-hidden="true"><span class="lw-tex"></span></span><span><b>' +
        t.weave[k] + '</b> · ' + t.kind[k] + '</span></li>';
    }).join('');
    var marks = [
      ['accept', KNOT.accept], ['object', KNOT.object], ['carried', knot('accept', true)],
      ['permission', PEG], ['error', SNAP], ['unfinished', FRAY], ['absent', '<span class="lw-swatch lw-swatch--bare"></span>']
    ].map(function (p) {
      return '<li><span class="lw-key-ico lw-key-ico--' + p[0] + '" aria-hidden="true">' + p[1] + '</span><span>' + t.mark[p[0]] + '</span></li>';
    }).join('');
    return '<section class="lw-key" data-key="key"><h3 class="lw-key-title">' + t.keyTitle + '</h3>' +
      '<p>' + t.key1 + '</p><p>' + t.key2 + '</p>' +
      '<div class="lw-key-cols"><div><span class="lw-eyebrow">' + t.keyKinds + '</span><ul class="lw-key-list">' + sw + '</ul></div>' +
      '<div><span class="lw-eyebrow">' + t.keyMarks + '</span><ul class="lw-key-list lw-key-marks">' + marks + '</ul></div></div></section>';
  }

  /* ------------------------------------------------------------- render */

  function render(model) {
    model = model && typeof model === 'object' ? model : {};
    var L = /^zh/i.test(str(model.language)) ? 'zh' : 'en';
    var t = T[L];
    var id = str(model.id);
    var m = mem(id);
    var now = Date.now();
    var agents = agentsOf(model);
    var N = agents.length;
    var rows = derive(model, agents, t);
    var status = statusKey(model.status);
    var running = !!model.running;
    var off = !running && !!OFF_LOOM[status];
    var last = rows.length - 1;

    var c = {
      t: t, model: model, m: m, agents: agents, N: N, rows: rows, status: status,
      running: running, off: off, halt: !running && !off,
      sel: rows.length ? Math.max(0, Math.min(last, toInt(model.index, last))) : -1,
      latest: rows.length ? Math.max(0, Math.min(last, toInt(model.latest, last))) : -1,
      ids: agents.map(function (a) { return a.id; }),
      calls: {}, busy: {}, beat: false
    };

    m.ids = c.ids;
    m.pullIdx = m.pull == null ? -1 : m.ids.indexOf(m.pull);
    if (m.pullIdx < 0) m.pull = null;

    /* motion bookkeeping: what is new, what just got woven */
    var fresh = 0;
    rows.forEach(function (row) {
      row.key = 'row-' + row.i + '-' + row.name;
      var first = m.seen.get(row.key);
      if (first == null) { first = now; m.seen.set(row.key, now); }
      row.isNew = now - first < NEW_MS;
      row.delay = row.isNew ? Math.min(fresh++, 11) : 0;
      row.seats.forEach(function (s) {
        s.key = 'cell-' + row.i + '-' + s.agent.id;
        var prev = m.prev.get(s.key);
        if (prev != null && prev !== s.state && WOVEN[s.state]) m.beat.set(s.key, now);
        m.prev.set(s.key, s.state);
        var b = m.beat.get(s.key);
        s.beat = !row.isNew && b != null && now - b < BEAT_MS;
        if (s.beat) c.beat = true;
        if (s.callId != null && !s.carried) c.calls[s.agent.id] = (c.calls[s.agent.id] || 0) + 1;
        if (s.state === 'writing') c.busy[s.agent.id] = 1;
      });
    });
    c.nowText = nowLine(c);
    var lastBallot = rows.findLastIndex(function (row) { return row.kind === 'ballot'; });

    m.base = ['lw', 'lw--n' + Math.max(1, Math.min(N, MAX_BANDS)), off ? 'lw--off' : 'lw--loom',
      running ? 'lw--live' : '', model.stopping ? 'lw--stopping' : '', c.halt ? 'lw--halt' : '',
      'lw--st-' + status, rows.length ? '' : 'lw--blank'].filter(Boolean).join(' ');

    return '<div class="' + m.base + pullCls(m) + '" lang="' + t.lang + '" data-lw-id="' + esc(id) + '" data-key="lw-root">' +
      '<div class="lw-stage">' +
        head(c) +
        '<div class="lw-body">' +
          '<div class="lw-loom">' + beam(c) + fan(c) + cloth(c) + fell(c) + hang(c) + '</div>' +
          '<div class="lw-side">' + verdict(c) + (c.sel >= 0 && !(c.off && c.sel === lastBallot) ? card(c, rows[c.sel], 'side') : '') + legend(c) + '</div>' +
        '</div>' +
      '</div></div>';
  }

  /* --------------------------------------------------------------- sync */

  var bound = typeof WeakSet === 'function' ? new WeakSet() : {
    has: function (r) { return !!r.__lwBound; },
    add: function (r) { r.__lwBound = true; }
  };

  function ctxOf(root) {
    var el = root.classList && root.classList.contains('lw') ? root : root.querySelector('.lw');
    if (!el) return null;
    var m = store[el.getAttribute('data-lw-id') || ''];
    return m ? { el: el, m: m } : null;
  }

  /* mirror exactly what render() would output for the new pull state */
  function setPull(el, m, id) {
    var k = id == null ? -1 : m.ids.indexOf(id);
    m.pull = k < 0 ? null : id;
    m.pullIdx = k;
    el.className = m.base + pullCls(m);
    var btns = el.querySelectorAll('[data-lw-thread]');
    for (var i = 0; i < btns.length; i++) {
      btns[i].setAttribute('aria-pressed', String(btns[i].getAttribute('data-lw-thread') === m.pull));
    }
  }

  function focusSpool(el, id) {
    var b = el.querySelectorAll('.lw-spool[data-lw-thread]');
    for (var i = 0; i < b.length; i++) {
      if (b[i].getAttribute('data-lw-thread') === id) { b[i].focus({ preventScroll: true }); return; }
    }
  }

  function markFocus(el, m) {
    var seats = el.querySelectorAll('.lw-seat');
    for (var i = 0; i < seats.length; i++) {
      var s = seats[i];
      var on = !!m.focus && s.getAttribute('data-lw-phase') === String(m.focus.i) && s.getAttribute('data-lw-agent') === m.focus.a;
      s.classList.toggle('lw-seat--focus', on);
    }
  }

  function bind(root) {
    var quietUntil = 0;

    root.addEventListener('click', function (e) {
      var c = ctxOf(root);
      var tgt = e.target && e.target.closest ? e.target : null;
      if (!c || !tgt) return;
      var th = tgt.closest('[data-lw-thread]');
      if (th) {
        if (Date.now() < quietUntil) return;
        var id = th.getAttribute('data-lw-thread');
        setPull(c.el, c.m, c.m.pull === id ? null : id);
        return;
      }
      if (tgt.closest('[data-visual-phase]')) {
        if (c.m.pull != null) setPull(c.el, c.m, null);
        return;
      }
      if (tgt.closest('button, a, .lw-say')) return;
      var cell = tgt.closest('.lw-cell');
      if (!cell || c.m.pull != null || !cell.hasAttribute('data-lw-phase')) return;
      c.m.focus = { i: Number(cell.getAttribute('data-lw-phase')), a: cell.getAttribute('data-lw-agent') };
      markFocus(c.el, c.m);
      var pick = cell.parentNode && cell.parentNode.querySelector('.lw-pick');
      if (pick) pick.click();
    });

    root.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape') return;
      var c = ctxOf(root);
      if (!c || c.m.pull == null) return;
      var id = c.m.pull;
      setPull(c.el, c.m, null);
      focusSpool(c.el, id);
    });

    /* drag a loom weight (or a fringe tassel) down to pull its thread */
    root.addEventListener('pointerdown', function (e) {
      if (e.button !== 0) return;
      var w = e.target && e.target.closest ? e.target.closest('.lw-weight') : null;
      if (!w) return;
      var y0 = e.clientY, dy = 0, pid = e.pointerId;
      try { w.setPointerCapture(pid); } catch (err) { /* capture is a nicety */ }
      w.classList.add('is-tug');
      function move(ev) {
        if (ev.pointerId !== pid) return;
        dy = Math.max(0, Math.min(110, ev.clientY - y0));
        w.style.setProperty('--lw-tug', dy + 'px');
      }
      function end(ev) {
        if (ev.pointerId !== pid) return;
        w.removeEventListener('pointermove', move);
        w.removeEventListener('pointerup', end);
        w.removeEventListener('pointercancel', end);
        w.classList.remove('is-tug');
        w.style.removeProperty('--lw-tug');
        if (dy > 6) quietUntil = Date.now() + 500;
        if (dy > 42 && ev.type === 'pointerup') {
          var c = ctxOf(root);
          if (c) setPull(c.el, c.m, w.getAttribute('data-lw-thread'));
        }
      }
      w.addEventListener('pointermove', move);
      w.addEventListener('pointerup', end);
      w.addEventListener('pointercancel', end);
    });
  }

  function sync(root) {
    if (!root || !root.querySelector) return;
    if (!bound.has(root)) { bound.add(root); bind(root); }
  }

  window.createDiscussionVisual = render;
  window.syncDiscussionVisual = sync;
})();
