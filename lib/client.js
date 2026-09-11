// @dsh-external/dsh-scientific-reading — 文献工作区（宿主右侧栏，纯 DOM 页面）
// 手写 lazy-CJS factory 格式（tsdown 不可用时的等价产物）；数据源：/sr/api/* 宿主路由
window.__ModuleLoader__.load({
  id: '@dsh-external/dsh-scientific-reading',
  factory: (require) => {
    var module = { exports: {} };
    var React = require('react');
    var exports = module.exports;
    Object.defineProperty(exports, Symbol.toStringTag, { value: 'Module' });

    // ── 工具函数 ─────────────────────────────────────────────
    function el(tag, cls, text) {
      var node = document.createElement(tag);
      if (cls) node.className = cls;
      if (text !== undefined) node.textContent = text;
      return node;
    }
    function userMessage(error) {
      var message = String(error && error.message || error || '');
      var messages = {
        model_policy_changed: '设置已更新，请刷新后重试。',
        reader_source_changed: '原文已更新，请重新打开阅读页。',
        reader_selection_changed: '选区已变化，请重新选择。',
        reader_selection_invalid: '请选择正文中的片段。',
        paper_not_found: '未找到这篇文献，请刷新文献库。',
        pdf_required: '请先添加 PDF。',
        assets_not_ready: '图表尚未整理。',
        request_forbidden: '页面已失效，请重新打开。',
        model_step_incomplete: '回答未完成，请重试。',
        display_theme_invalid: '请选择一种主题。',
        native_session_request_failed: '暂时无法打开对话，请重试。',
        xlsx_locked: '请保存并关闭 Excel 后重试。'
      };
      if (messages[message]) return messages[message];
      if (/changed|conflict|revision/.test(message)) return '内容已更新，请刷新后重试。';
      if (/xlsx.*(?:busy|locked|permission)|PermissionError/.test(message)) return '请保存并关闭 Excel 后重试。';
      if (/template|css_|reader_appearance/.test(message)) return '模板无法使用，请检查内容或恢复默认。';
      return /[\u3400-\u9fff]/.test(message) && !/[{}]|Traceback|Error:/.test(message) ? message : '暂时无法完成，请重试。';
    }
    function modelOptionLabel(model, models) {
      var label = model.name || model.id;
      var duplicates = models.filter(function (item) { return item.id === model.id && item.name === model.name; });
      if (duplicates.length < 2) return label;
      return label + '（' + (model.providerName || model.provider) + '）';
    }
    function sourceLabel(value) {
      return {europe_pmc:'Europe PMC',crossref:'Crossref',recent:'近期研究',incremental:'新增研究',classic:'较早研究',classics:'较早研究',counter:'相反结果',counterevidence:'相反结果',title:'题名',abstract_en:'英文摘要',abstract_zh:'中文摘要',journal:'期刊',year:'年份'}[value] || '';
    }
    function publicationStatus(value) {
      if (/retracted publication/i.test(value)) return '已撤稿';
      if (/retract/i.test(value)) return '撤稿通知';
      if (/erratum|correct/i.test(value)) return '更正通知';
      if (/preprint/i.test(value)) return '预印本';
      return /^update_notice:/.test(value) ? '出版更新通知' : value;
    }
    function readingStatus(value) {
      var labels = {ready:'已完成',completed:'已完成',success:'已完成',missing:'待补摘要',pending:'待处理',queued:'排队中',running:'处理中',waiting_agent:'等待生成',waiting_user:'需要补充材料',needs_user:'需要补充材料',failed:'处理失败',interrupted:'已中断',canceled:'已取消',not_started:'未开始'};
      return labels[value] || (/[\u3400-\u9fff]/.test(value || '') ? value : value ? '状态待确认' : '未开始');
    }
    function searchMatchModel(match) {
      if (!match || typeof match !== 'object' || typeof match.snippet !== 'string' || !match.snippet.trim()) return null;
      var kindLabels = { metadata: '文献信息', abstract_en: '英文摘要', abstract_zh: '中文摘要', conclusion: '已确认结论', personal: '个人记录' };
      if (!Object.prototype.hasOwnProperty.call(kindLabels, match.content_type)) return null;
      var model = { kind: match.content_type, kindLabel: kindLabels[match.content_type], snippet: match.snippet.trim(), basisLabel: '', evidenceLabel: '', validityLabel: '', evidenceHref: '' };
      if (match.content_type !== 'conclusion') return model;
      var basisLabels = { paper: '论文定位', personal: '个人判断', inference: '推断', question: '待核问题', legacy: '旧版记录' };
      var evidenceLabels = { location_verified: '定位有效', stale: '定位失效', legacy_unverified: '旧版未验证', not_provided: '未提供定位' };
      model.basisLabel = Object.prototype.hasOwnProperty.call(basisLabels, match.basis) ? basisLabels[match.basis] : '未标注';
      model.evidenceLabel = Object.prototype.hasOwnProperty.call(evidenceLabels, match.evidence_status) ? evidenceLabels[match.evidence_status] : '定位状态未知';
      model.validityLabel = '结论待核对';
      var conclusionId = typeof match.conclusion_id === 'string' && /^review_[0-9a-f]{32}$/.test(match.conclusion_id) ? match.conclusion_id : '';
      var expectedHref = conclusionId ? '/sr/evidence?conclusion_id=' + encodeURIComponent(conclusionId) : '';
      if (conclusionId && match.basis === 'paper' && match.evidence_status === 'location_verified' && match.claim_support === 'location_only' && match.evidence_url === expectedHref) model.evidenceHref = expectedHref;
      return model;
    }
    function renderSearchMatches(paper) {
      var matches = Array.isArray(paper.search_matches) ? paper.search_matches.map(searchMatchModel).filter(Boolean) : [];
      if (!matches.length) return null;
      var section = el('section', 'sr-search-matches');
      section.setAttribute('aria-label', '检索命中');
      matches.forEach(function (match) {
        var row = el('div', 'sr-search-match');
        var head = el('div', 'sr-search-match-head');
        head.appendChild(el('span', 'sr-search-kind', match.kindLabel));
        if (match.kind === 'conclusion') {
          head.appendChild(el('span', 'sr-search-basis', '依据：' + match.basisLabel));
          head.appendChild(el('span', 'sr-search-evidence-status', match.evidenceLabel));
          head.appendChild(el('span', 'sr-search-validity', match.validityLabel));
        }
        row.appendChild(head);
        row.appendChild(el('p', 'sr-search-snippet', match.snippet));
        if (match.evidenceHref) {
          var link = el('a', 'sr-search-evidence', '查看原文');
          link.href = match.evidenceHref;
          link.target = '_blank';
          link.rel = 'noopener';
          row.appendChild(link);
        }
        section.appendChild(row);
      });
      return section;
    }
    function btn(text, onClick, cls) {
      var b = el('button', cls || 'sr-btn', text);
      b.addEventListener('click', onClick);
      return b;
    }
    async function api(path, options) {
      var res = await fetch(path, options);
      var text = await res.text();
      var data = null;
      try { data = JSON.parse(text) } catch (e) { data = { error: text.slice(0, 200) } }
      if (!res.ok) throw new Error(data.error || ('HTTP ' + res.status));
      return data;
    }
    function applyTheme(root, theme) {
      if (!theme || !/^#[0-9a-f]{6}$/i.test(theme.accent)) return;
      var rgb=[1,3,5].map(function(i){var v=parseInt(theme.accent.slice(i,i+2),16)/255;return v<=0.04045?v/12.92:Math.pow((v+0.055)/1.055,2.4);});
      var luminance=0.2126*rgb[0]+0.7152*rgb[1]+0.0722*rgb[2];
      root.style.setProperty('--sr-accent',theme.accent);
      root.style.setProperty('--sr-accent-text',luminance>0.179?'#172a31':'#ffffff');
      var tokens = {canvas:'bg',paper:'surface',ink:'text',muted:'muted',line:'line',sidebar:'sidebar-bg',hover:'hover'};
      Object.keys(tokens).forEach(function (key) {
        if (/^#[0-9a-f]{6}$/i.test(theme[key] || '')) root.style.setProperty('--sr-' + tokens[key], theme[key]);
      });
      root.style.colorScheme = theme.scheme === 'dark' ? 'dark' : 'light';
      root.dataset.theme = theme.id || 'paper';
    }
    // 工作台、设置和弹窗共用阅读器的暖纸色与控件尺度；主题色由 applyTheme 覆盖。
    var UI_STYLES = `
      .sr-root,.sr-settings-page{--sr-bg:#f3f1eb;--sr-surface:#fffef9;--sr-text:#252822;--sr-muted:#6e726a;--sr-line:#d9d6ca;--sr-accent:#405f54;--sr-accent-text:#fff;--sr-hover:#e9eee8;--sr-radius:8px;--sr-font-ui:"Source Han Sans SC","Noto Sans CJK SC","Microsoft YaHei",sans-serif;--sr-font-heading:Georgia,"Source Han Serif SC","Noto Serif CJK SC","Songti SC",serif;font:14px/1.6 var(--sr-font-ui);color-scheme:light}
      .sr-root *,.sr-settings-page *{box-sizing:border-box}
      .sr-root :focus-visible,.sr-settings-page :focus-visible{outline:2px solid var(--sr-accent);outline-offset:3px}
      .sr-root :is(input,select,textarea),.sr-settings-page :is(input,select,textarea){min-width:0;max-width:100%;border:1px solid var(--sr-line);border-radius:var(--sr-radius);padding:7px 10px;background:var(--sr-surface);color:var(--sr-text);font:inherit;line-height:1.5;accent-color:var(--sr-accent)}
      .sr-root :is(input,select):not([type=checkbox]):not([type=radio]),.sr-settings-page :is(input,select):not([type=checkbox]):not([type=radio]){min-height:36px}
      .sr-root :is(input[type=checkbox],input[type=radio]){width:16px;height:16px;flex:none}
      .sr-root textarea,.sr-settings-page textarea{resize:vertical}
      .sr-settings-page input[type=color]{width:44px;padding:4px;cursor:pointer}
      .sr-root :is(.sr-btn,.sr-entry,.sr-toggle),.sr-settings-page button,.sr-settings-page .sr-settings-link{display:inline-flex;justify-content:center;align-items:center;gap:6px;min-height:36px;height:auto;padding:7px 12px;border:1px solid var(--sr-line);border-radius:var(--sr-radius);background:var(--sr-surface);color:var(--sr-text);font:500 13px/1.5 var(--sr-font-ui);text-decoration:none;cursor:pointer;transition:background .14s,border-color .14s}
      .sr-root .sr-toggle{width:34px;min-height:34px;padding:4px}
      .sr-root :is(.sr-btn,.sr-entry,.sr-nav-item):hover:not(:disabled),.sr-settings-page button:hover:not(:disabled),.sr-settings-page .sr-settings-link:hover{background:var(--sr-hover);border-color:var(--sr-accent)}
      .sr-root .sr-btn-primary,.sr-settings-page .sr-settings-primary{background:var(--sr-accent);border-color:var(--sr-accent);color:var(--sr-accent-text)}
      .sr-root .sr-btn-primary:hover:not(:disabled),.sr-settings-page .sr-settings-primary:hover:not(:disabled){background:var(--sr-accent);color:var(--sr-accent-text);filter:brightness(.94)}
      .sr-root button:disabled,.sr-settings-page button:disabled{opacity:.5;cursor:not-allowed}
      .sr-root .sr-sidebar{background:#ebe8df;padding:20px 12px;overflow-y:auto;scrollbar-width:thin}
      .sr-root .sr-brand{font-family:var(--sr-font-heading);letter-spacing:.06em}
      .sr-root .sr-nav-item{border-color:transparent;background:transparent;font:500 13px/1.5 var(--sr-font-ui);min-height:38px;border-radius:var(--sr-radius)}
      .sr-root .sr-nav-item[aria-current=true]{background:var(--sr-surface);border-color:var(--sr-line);box-shadow:inset 3px 0 var(--sr-accent);color:var(--sr-text)}
      .sr-root .sr-paper-row{padding:14px 16px;gap:12px}.sr-root .sr-paper-row:hover{background:#f5f6ef}
      .sr-root .sr-paper-title{font:600 16px/1.5 var(--sr-font-heading)}
      .sr-root .sr-tag,.sr-root .sr-tag-more{background:var(--sr-hover);color:var(--sr-muted)}
      .sr-root .sr-btn-mark{box-shadow:none}.sr-root .sr-entry{white-space:normal;text-align:center}
      .sr-root .sr-drawer-actions{flex-wrap:wrap;gap:8px}.sr-root .sr-drawer h2{font:600 25px/1.45 var(--sr-font-heading);overflow-wrap:anywhere}
      .sr-root .sr-ingest-dialog{border-radius:14px}.sr-root .sr-ingest-dialog h2{font:600 24px/1.4 var(--sr-font-heading)}
      .sr-settings-page{background:var(--sr-bg);padding:32px clamp(16px,4vw,48px) calc(var(--dsh-composer-height,126px) + 32px)}
      .sr-settings-page .sr-settings-shell{max-width:1000px}.sr-settings-page .sr-settings-head{margin-bottom:28px;gap:16px}
      .sr-settings-page .sr-settings-head h1{font:600 30px/1.35 var(--sr-font-heading);letter-spacing:0}
      .sr-settings-page .sr-settings-group{margin-top:20px;padding:22px 24px;background:var(--sr-surface);border:1px solid var(--sr-line);border-radius:12px}
      .sr-settings-page .sr-settings-group h2{font:600 17px/1.5 var(--sr-font-heading);color:var(--sr-text);padding-bottom:14px}
      .sr-settings-page .sr-settings-group>p{font-size:13px;color:var(--sr-muted);margin:14px 0}
      .sr-settings-page .sr-setting-row{grid-template-columns:minmax(150px,.8fr) minmax(0,1.5fr);gap:20px;padding:16px 0}
      .sr-settings-page .sr-setting-control>div:not(.sr-model-step-controls){display:flex;align-items:center;flex-wrap:wrap;gap:8px;min-width:0;max-width:100%}
      .sr-settings-page .sr-model-step-controls{display:grid;grid-template-columns:minmax(0,1fr) 105px auto;width:100%;gap:8px}
      .sr-settings-page .sr-model-step-controls select{width:100%;font-size:13px}
      .sr-settings-page .sr-model-step-controls .sr-settings-note{grid-column:1/-1;margin:0}
      .sr-settings-page .sr-settings-secondary{min-height:32px;padding:4px 0;background:transparent;border:0;color:var(--sr-muted)}
      .sr-root .sr-dialog{max-width:calc(100vw - 24px);max-height:90dvh;overflow:auto;overscroll-behavior:contain;padding:28px;border:1px solid var(--sr-line);border-radius:14px;background:var(--sr-surface);color:var(--sr-text);box-shadow:0 18px 60px #25282226;font:14px/1.65 var(--sr-font-ui)}
      .sr-root .sr-dialog::backdrop{background:#25282255}
      .sr-dialog h2{margin:0 0 8px;font:600 26px/1.4 var(--sr-font-heading)}.sr-dialog h3{font-size:16px;margin:24px 0 12px}
      .sr-dialog>p{color:var(--sr-muted);margin:8px 0 20px;overflow-wrap:anywhere}
      .sr-dialog :is(summary,label){font-weight:500}.sr-dialog details{margin:16px 0}.sr-dialog summary{padding:8px 0;cursor:pointer}
      .sr-dialog .sr-form-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(220px,100%),1fr));gap:14px;margin:18px 0;align-items:end}
      .sr-form-grid label{display:flex;flex-direction:column;gap:6px;min-width:0}.sr-form-grid :is(input,select,textarea){width:100%}
      .sr-dialog>.sr-btn{margin:0 8px 8px 0}.sr-dialog .sr-query-preview{padding:14px 16px;background:var(--sr-bg);border:1px solid var(--sr-line);border-radius:var(--sr-radius);overflow-wrap:anywhere}
      .sr-dialog .sr-radar-candidate{padding:22px 0;border-top:1px solid var(--sr-line)}.sr-radar-candidate h4{font:600 19px/1.5 var(--sr-font-heading);margin:0 0 10px}
      .sr-table-scroll{max-width:100%;overflow-x:auto;overscroll-behavior:contain;margin:18px 0}.sr-table-scroll table{width:100%;min-width:610px;border-collapse:collapse;font-size:13px}
      .sr-view-columns th{padding:10px 6px;text-align:left;color:var(--sr-muted);font-weight:500;border-bottom:1px solid var(--sr-line)}.sr-view-columns td{border-bottom:1px solid var(--sr-line)}
      .sr-view-columns .sr-btn{min-height:30px;padding:3px 9px;margin:2px}
      @container(max-width:690px){.sr-settings-page .sr-setting-row{grid-template-columns:1fr;gap:10px}.sr-settings-page .sr-setting-control{justify-content:flex-start;width:100%}.sr-settings-page .sr-settings-group{padding:18px 16px}.sr-settings-page .sr-setting-path{text-align:left}.sr-settings-page .sr-settings-head h1{font-size:26px}}
      @container(max-width:410px){.sr-settings-page .sr-model-step-controls{grid-template-columns:minmax(0,1fr) auto}.sr-model-step-controls select:first-child{grid-column:1/-1}}
      @media(max-width:680px){.sr-root .sr-main{padding:12px 10px calc(var(--dsh-composer-height,126px) + 12px)}.sr-root .sr-search{min-width:0;flex-basis:100%}.sr-root .sr-paper-row{padding:12px 10px;gap:8px}.sr-root .sr-row-actions{flex-wrap:wrap}.sr-root .sr-dialog{padding:20px 16px}.sr-dialog h2{font-size:23px}.sr-root .sr-drawer{padding:20px 16px}.sr-root .sr-toolbar{gap:8px}.sr-settings-page .sr-settings-head{flex-wrap:wrap}.sr-root .sr-filter{min-width:0;flex:1 1 100px}.sr-root .sr-sidebar{padding:16px 8px}}
      @media(prefers-reduced-motion:reduce){.sr-root *,.sr-settings-page *{transition:none!important;scroll-behavior:auto!important}}
      .sr-root .sr-sidebar{background:var(--sr-sidebar-bg,#ebe8df)}
      .sr-root .sr-paper-row:hover,.sr-root .sr-entry:hover:not(:disabled),.sr-settings-page button:hover{background:var(--sr-hover)}
      .sr-root :is(.sr-tag,.sr-tag-more,.sr-folder-chip,.sr-search-match,.sr-search-kind,.sr-search-basis,.sr-search-evidence-status,.sr-search-validity){background:var(--sr-hover);color:var(--sr-muted)}
      .sr-root .sr-entry:disabled{background:var(--sr-bg);color:var(--sr-muted)}
      .sr-theme-choices{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-top:20px}
      .sr-theme-card{position:relative;display:grid;gap:8px;padding:8px;border:1px solid var(--sr-line);border-radius:10px;cursor:pointer;background:var(--sr-surface)}
      .sr-theme-card:has(input:checked){outline:2px solid var(--sr-accent);outline-offset:2px}.sr-theme-card:focus-within{outline:2px solid var(--sr-accent);outline-offset:3px}
      .sr-theme-card input{position:absolute;opacity:0;width:1px;height:1px}.sr-theme-card:has(input:disabled){opacity:.65;cursor:wait}
      .sr-theme-name{font-size:13px;text-align:center}.sr-theme-preview{height:76px;display:grid;grid-template-columns:1fr 3fr;gap:8px;padding:10px;border:1px solid var(--sr-line);border-radius:5px;background:var(--sr-bg)}
      .sr-theme-preview-rail{border-radius:2px;background:var(--sr-sidebar-bg);border-top:5px solid var(--sr-accent)}
      .sr-theme-preview-page{position:relative;background:var(--sr-surface);border:1px solid var(--sr-line);border-radius:2px}
      .sr-theme-preview-page:before{content:'';position:absolute;left:9px;right:9px;top:12px;height:3px;background:var(--sr-text);box-shadow:0 9px 0 var(--sr-muted),0 18px 0 var(--sr-line)}
      .sr-workbench-panel{height:100%;min-width:0;overflow:auto;overscroll-behavior:contain;container:sr-workbench / inline-size}
      .sr-workbench-panel>.sr-settings-page{padding:20px 20px 36px;min-height:100%}.sr-workbench-panel>.sr-settings-page .sr-settings-head{display:none}
      .sr-workbench-panel .sr-root{height:auto;min-height:100%}.sr-workbench-panel .sr-root .sr-main{padding-bottom:24px}
      @container sr-workbench (max-width:760px){.sr-workbench-panel .sr-root{display:block;overflow:visible}.sr-workbench-panel .sr-sidebar{display:flex;flex-wrap:wrap;align-items:center;gap:6px;max-height:160px;overflow:auto;border-bottom:1px solid var(--sr-line);border-right:0;padding:12px}.sr-workbench-panel .sr-sidebar-head{display:none}.sr-workbench-panel .sr-nav-item{width:auto;margin:0}.sr-workbench-panel .sr-folder-list{display:contents}.sr-workbench-panel .sr-folder-title{margin:4px}.sr-workbench-panel .sr-main{padding:16px}.sr-workbench-panel .sr-paper-row{grid-template-columns:24px minmax(0,1fr)}.sr-workbench-panel .sr-row-actions{grid-column:2;justify-content:flex-start;flex-wrap:wrap}}
      @container(max-width:550px){.sr-theme-choices{grid-template-columns:repeat(2,minmax(0,1fr))}}
    `;
    function createMountController(createMount) {
      var mount = null;
      var host = null;
      function cleanup() {
        if (!mount) return;
        var currentMount = mount;
        var currentHost = host;
        mount = null;
        host = null;
        currentMount.dispose();
        if (currentHost) {
          if (currentMount.root && currentMount.root.parentNode === currentHost) currentHost.removeChild(currentMount.root);
          delete currentHost.dataset.srMounted;
        }
      }
      function literatureRef(node) {
        if (!node) { cleanup(); return; }
        if (node === host && mount) return;
        cleanup();
        host = node;
        mount = createMount();
        node.dataset.srMounted = '1';
        node.appendChild(mount.root);
      }
      return { ref: literatureRef, cleanup: cleanup };
    }
    function createDrawerSessionController() {
      var token = 0; var paperId = ''; var readers = new Set();
      function close() { token += 1; paperId = ''; readers.forEach(function (reader) { try { reader.abort(); } catch (e) {} }); readers.clear(); }
      return {
        open: function (nextPaperId) { close(); paperId = nextPaperId; return token; },
        close: close,
        isCurrent: function (session, expectedPaperId) { return session === token && expectedPaperId === paperId && !!paperId; },
        guard: function (session, expectedPaperId, callback) { if (session === token && expectedPaperId === paperId && paperId) return callback(); },
        trackReader: function (session, expectedPaperId, reader) { if (session === token && expectedPaperId === paperId) readers.add(reader); },
        releaseReader: function (reader) { readers.delete(reader); },
      };
    }
    function nextDialogFocus(focusables, current, backwards) {
      if (!focusables.length) return null;
      var index = focusables.indexOf(current); if (index < 0) index = backwards ? 0 : -1;
      return focusables[(index + (backwards ? -1 : 1) + focusables.length) % focusables.length];
    }
    function normalizeIngestTitles(value, batch) {
      if (!batch) {
        var title = String(value || '').trim().replace(/\s+/g, ' ');
        return title ? [title] : [];
      }
      var seen = new Set();
      return String(value || '').split(/\r?\n/).map(function (title) { return title.trim(); }).filter(function (title) {
        if (!title || seen.has(title)) return false;
        seen.add(title);
        return true;
      });
    }
    function createLiteratureLifecycle(drawerSessions, drawerActions, rowActions) {
      return {
        closeDrawerScope: function () { drawerSessions.close(); drawerActions.close(); },
        dispose: function () { drawerSessions.close(); drawerActions.dispose(); rowActions.dispose(); },
      };
    }
    function createReviewSessionController(deps) {
      var pending = new Map(); var disposed = false;
      return {
        open: function (paperId) {
          var snapshot = deps.sessions && deps.sessions.list && deps.sessions.list.getSnapshot();
          var parentSessionId = snapshot && snapshot.current;
          if (typeof parentSessionId !== 'string' || !parentSessionId) return Promise.reject(new Error('literature_parent_session_required'));
          var key = JSON.stringify([parentSessionId, paperId]);
          if (pending.has(key)) return pending.get(key);
          var task = deps.api('/sr/api/reviews/open', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'x-sr-csrf': '1' },
            body: JSON.stringify({ parent_session_id: parentSessionId, paper_id: paperId }),
          }).then(function (result) {
            if (!result || typeof result.review_session_id !== 'string') throw new Error('review_session_invalid');
            return Promise.resolve(deps.sessions.refreshSubagents(parentSessionId)).then(function () {
              if (disposed) return result;
              deps.sessions.openSubagent({ parentSessionId: parentSessionId, childSessionId: result.review_session_id, mode: 'continuable' });
              return result;
            });
          });
          pending.set(key, task);
          task.finally(function () { if (pending.get(key) === task) pending.delete(key); }).catch(function () {});
          return task;
        },
        dispose: function () { disposed = true; },
      };
    }
    function createSelectionStore() {
      var selected = new Set(); var revisions = new Map();
      return {
        toggle: function (paperId, checked) { revisions.set(paperId, (revisions.get(paperId) || 0) + 1); if (checked) selected.add(paperId); else selected.delete(paperId); },
        replacePage: function () {},
        remove: function (paperIds) { paperIds.forEach(function (paperId) { selected.delete(paperId); }); },
        snapshot: function () { return Array.from(selected).map(function (paperId) { return { paper_id: paperId, revision: revisions.get(paperId) || 0 }; }); },
        removeSnapshot: function (snapshot, paperIds) { var successful = new Set(paperIds); snapshot.forEach(function (entry) { if (successful.has(entry.paper_id) && selected.has(entry.paper_id) && revisions.get(entry.paper_id) === entry.revision) selected.delete(entry.paper_id); }); },
        values: function () { return Array.from(selected); },
        size: function () { return selected.size; },
        clear: function () { selected.clear(); },
      };
    }
    function createPaperSessionController(deps) {
      var pending = new Map(); var disposed = false;
      return {
        open: function (paperId) {
          if (pending.has(paperId)) return pending.get(paperId);
          var task = deps.api('/sr/api/chats/open', { method: 'POST',
            headers: { 'Content-Type': 'application/json', 'x-sr-csrf': '1' }, body: JSON.stringify({ paper_id: paperId })
          }).then(async function (result) {
            if (!result || typeof result.session_id !== 'string') throw new Error('paper_chat_invalid');
            await deps.sessions.refresh();
            if (!disposed) deps.sessions.open(result.session_id);
            return result;
          });
          pending.set(paperId, task);
          task.finally(function () { pending.delete(paperId); }).catch(function () {});
          return task;
        },
        dispose: function () { disposed = true; },
      };
    }
    function createBatchController(deps) {
      var active = null; var sequence = 0; var disposed = false;
      return {
        submit: function (action, payload) {
          if (disposed) return Promise.reject(new Error('batch_controller_disposed'));
          if (active) return Promise.reject(new Error('batch_action_in_progress'));
          var snapshot = deps.selection.snapshot(); var selected = snapshot.map(function (entry) { return entry.paper_id; });
          if (!selected.length) return Promise.resolve(null);
          var current = ++sequence; var controller = new AbortController(); active = controller;
          return deps.api('/sr/api/batch', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: controller.signal,
            body: JSON.stringify({ action: action, selection: selected, payload: payload || {} }),
          }).then(function (result) {
            if (disposed || current !== sequence) return result;
            var children = Array.isArray(result.children) ? result.children : [];
            deps.selection.removeSnapshot(snapshot, children.filter(function (child) { return child.status === 'created' || child.status === 'reused'; }).map(function (child) { return child.paper_id; }));
            var summary = result.summary || {};
            var pending = (summary.needs_user || 0) + (summary.pending || 0);
            var message;
            if (result.status === 'failed') {
              message = '批量操作未完成：成功 ' + ((summary.created || 0) + (summary.reused || 0)) + '｜待处理 ' + pending + '｜失败 ' + (summary.failed || 0);
            } else if (result.status === 'running') {
              message = '批量处理中：待处理 ' + pending;
            } else {
              message = '批量完成：成功 ' + ((summary.created || 0) + (summary.reused || 0)) + '｜待处理 ' + pending + '｜失败 ' + (summary.failed || 0);
            }
            deps.onSummary(message, result);
            return result;
          }).finally(function () { if (active === controller) active = null; });
        },
        dispose: function () { disposed = true; sequence += 1; if (active) active.abort(); active = null; },
      };
    }
    function isSafeHttpUrl(value) {
      try {
        var parsed = new URL(String(value));
        return (parsed.protocol === 'http:' || parsed.protocol === 'https:') && !!parsed.hostname;
      } catch (e) { return false; }
    }
    function pairAbstractParagraphs(english, chinese) {
      var en = String(english || '').split(/\n\s*\n/).map(function (x) { return x.trim(); }).filter(Boolean);
      var zh = String(chinese || '').split(/\n\s*\n/).map(function (x) { return x.trim(); }).filter(Boolean);
      return Array.from({ length: Math.max(en.length, zh.length) }, function (_, index) {
        return { en: en[index] || '', zh: zh[index] || '' };
      });
    }
    function paperEntryModel(paper, validateUrl) {
      return {
        pdf: paper.has_pdf
          ? { label: '打开 PDF', href: '/sr/api/paper/', action: 'open', external: true, disabledReason: '' }
          : { label: '获取 PDF', href: '', action: 'download', disabledReason: '' },
        html: paper.has_reader
          ? { label: '打开 HTML', href: '/sr/reader/', action: 'open', disabledReason: '' }
          : { label: '打开 HTML', href: '', action: 'none', disabledReason: '尚未生成精读 HTML' },
        excel: { label: '定位 Excel', href: '', action: 'locate', disabledReason: '' },
      };
    }
    function updateMineruKey(request, value) {
      var deleting = value === null;
      var options = {
        method: deleting ? 'DELETE' : 'POST',
        headers: { 'Content-Type': 'application/json', 'x-sr-csrf': '1' },
      };
      if (!deleting) options.body = JSON.stringify({ api_key: value });
      return request('/sr/api/settings/mineru-key', options).then(function () {
        return request('/sr/api/settings/recheck', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'x-sr-csrf': '1' },
          body: JSON.stringify({ targets: ['mineru_api'] }),
        });
      });
    }
    function createPaperActionController(deps) {
      var detailCache = new Map();
      var activeControllers = new Set();
      var pollTimer = null;
      var pollSequence = 0;
      var disposed = false;
      var schedule = deps.schedule || function (fn) { return setTimeout(fn, 800); };
      var cancel = deps.cancel || clearTimeout;
      function trackedApi(path, options) {
        var controller = new AbortController(); activeControllers.add(controller);
        return deps.api(path, Object.assign({}, options || {}, { signal: controller.signal })).finally(function () { activeControllers.delete(controller); });
      }
      function stop() {
        pollSequence += 1;
        if (pollTimer !== null) cancel(pollTimer);
        pollTimer = null;
        activeControllers.forEach(function (controller) { controller.abort(); });
        activeControllers.clear();
      }
      function loadDetail(paperId) {
        if (detailCache.has(paperId)) return detailCache.get(paperId);
        var promise = trackedApi('/sr/api/paper/' + encodeURIComponent(paperId)).then(function (detail) {
          var item = detail.item || {};
          return { detail: detail, abstract: { abstract_en: item.abstract_en, abstract_zh: item.abstract_zh, status: item.abstract_status, last_error: item.last_error } };
        }).catch(function (error) { detailCache.delete(paperId); throw error; });
        detailCache.set(paperId, promise);
        return promise;
      }
      function poll(paperId, jobId, sequence, onSuccess, onFailure) {
        if (disposed || sequence !== pollSequence) return Promise.resolve();
        return trackedApi('/sr/api/job/' + encodeURIComponent(jobId)).then(function (job) {
          if (disposed || sequence !== pollSequence) return;
          var detail = job.detail || {};
          var status = job.status || job.state || '';
          if (status === 'waiting_user') return onFailure(job);
          if (['completed', 'succeeded', 'ready', 'full_read_ready', 'exported'].includes(status)) { return onSuccess(); }
          if (['failed', 'cancelled'].includes(status)) return onFailure(job);
          pollTimer = schedule(function () { return runPoll(paperId, jobId, sequence, onSuccess, onFailure); });
        });
      }
      function runPoll(paperId, jobId, sequence, onSuccess, onFailure) {
        return poll(paperId, jobId, sequence, onSuccess, onFailure).catch(function (error) {
          if (error && error.name === 'AbortError') return;
          if (!disposed && sequence === pollSequence) onFailure({ status: 'failed', error: error && error.message ? error.message : '任务状态读取失败' });
        });
      }
      function startFullRead(paperId) {
        var sequence = ++pollSequence;
        return trackedApi('/sr/api/paper/' + encodeURIComponent(paperId) + '/full-read', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).then(function (result) {
          if (disposed || sequence !== pollSequence) return result;
          var jobId = result.parent_job_id;
          if (!/^job_[0-9a-f]{16}$/.test(String(jobId || ''))) throw new Error('任务编号无效');
          deps.onPatch(paperId, { full_read_status: 'queued', active_job_id: jobId });
          function onFailure(job) { var detail = job.detail || {}; deps.onPatch(paperId, job.status === 'waiting_user' ? { full_read_status: 'needs_user', needsUser: detail.reason_code === 'pdf_required', pdfRequired: detail.reason_code === 'pdf_required', active_job_id: jobId } : { full_read_status: 'failed', last_error: job.error || '任务失败' }); }
          pollTimer = schedule(function () { return runPoll(paperId, jobId, sequence, function () { return deps.onRefresh(paperId); }, onFailure); });
          return result;
        });
      }
      function exportAssets(paperId, context) {
        var sequence = ++pollSequence;
        return trackedApi('/sr/api/paper/' + encodeURIComponent(paperId) + '/export-assets', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
          .then(function (result) {
            if (disposed || sequence !== pollSequence) return result;
            function readAssets() { return trackedApi('/sr/api/paper/' + encodeURIComponent(paperId) + '/assets').then(function (assets) { if (!disposed && sequence === pollSequence && deps.onAssets) deps.onAssets(paperId, assets, context); return assets; }); }
            function exportFailure(job) { if (deps.onAssetsError) deps.onAssetsError(paperId, job.error || '资产导出失败', context); }
            if (!result.parent_job_id) return readAssets();
            if (!/^job_[0-9a-f]{16}$/.test(String(result.parent_job_id))) throw new Error('任务编号无效');
            pollTimer = schedule(function () { return runPoll(paperId, result.parent_job_id, sequence, readAssets, exportFailure); });
            return result;
          });
      }
      function loadAssets(paperId, context) { return trackedApi('/sr/api/paper/' + encodeURIComponent(paperId) + '/assets').then(function (assets) { if (deps.onAssets) deps.onAssets(paperId, assets, context); return assets; }).catch(function (error) { if (error.name !== 'AbortError' && deps.onAssetsError) deps.onAssetsError(paperId, error.message === 'assets_not_ready' ? '尚未整理' : error.message, context); }); }
      function oaDownload(paperId, jobId, identifier) {
        return trackedApi('/sr/api/paper/' + encodeURIComponent(paperId) + '/download', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ job_id: jobId, identifier: identifier }) }).then(function (result) { detailCache.delete(paperId); return result; });
      }
      function attachPdf(paperId, jobId, pdfBase64) {
        return trackedApi('/sr/api/paper/' + encodeURIComponent(paperId) + '/attach', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ job_id: jobId, pdf_b64: pdfBase64 }) }).then(function (result) { detailCache.delete(paperId); return result; });
      }
      return { loadDetail: loadDetail, loadAssets: loadAssets, invalidate: function (paperId) { detailCache.delete(paperId); }, startFullRead: startFullRead, exportAssets: exportAssets, oaDownload: oaDownload, attachPdf: attachPdf, close: stop, dispose: function () { disposed = true; stop(); detailCache.clear(); } };
    }
    // ── Phase 3 两栏文献导航 ──────────────────────────────────
    function renderLiterature(sessions, openSettings) {
      var disposed = false;
      var request = null;
      var requestSequence = 0;
      var searchTimer = null;
      var tagTimer = null;
      var state = { items: [], total: 0, folders: [], status: 'idle', error: '' };
      var controls = {};
      var drawerOpener = null;
      var drawerSessions = createDrawerSessionController();
      var ingestMode = 'single';
      var ingestOpener = null;
      var ingestSubmitting = false;
      var ingestRequest = null;
      var paperSessions = createPaperSessionController({ sessions: sessions, api: api });
      var viewsDialog = null;
      function postView(payload) {
        return api('/sr/api/views', {method:'POST', headers:{'Content-Type':'application/json','x-sr-csrf':'1'}, body:JSON.stringify(payload)});
      }
      function openViewsEditor() {
        if (viewsDialog) { viewsDialog.showModal(); return; }
        var dialog = el('dialog', 'sr-dialog sr-views-dialog'); viewsDialog = dialog;
        dialog.style.width = '960px';
        dialog.appendChild(el('h2', '', 'Excel 设置'));
        dialog.appendChild(el('p', '', '选择适用范围，调整表格列。'));
        var scope = document.createElement('select'); scope.setAttribute('aria-label', '显示方案范围');
        scope.appendChild(new Option('全局', ''));
        state.folders.forEach(function (folder) { scope.appendChild(new Option(folder.name, folder.folder_id)); });
        scope.value = state.folders.some(function (folder) { return folder.folder_id === queryStore.get().folder; }) ? queryStore.get().folder : '';
        var selector = document.createElement('select'); selector.setAttribute('aria-label', '已保存方案');
        var name = document.createElement('input'); name.setAttribute('aria-label', '方案名称'); name.value = '我的文献视图'; name.maxLength = 80;
        var form = el('div', 'sr-form-grid'); form.append(scope, selector, name); dialog.appendChild(form);
        var tableScroll = el('div', 'sr-table-scroll'); tableScroll.tabIndex = 0; tableScroll.setAttribute('aria-label','Excel 列设置'); dialog.appendChild(tableScroll);
        var table = el('table', 'sr-view-columns'); tableScroll.appendChild(table);
        var notice = el('p', 'sr-view-status'); notice.setAttribute('role','status'); dialog.appendChild(notice);
        var data, rows = [], selected = null, busy = false;
        function renderColumns(config) {
          var byId = new Map(data.fields.map(function (field) { return [field.field_id, field]; }));
          var supplied = config && config.columns || [];
          var ids = new Set(supplied.map(function (row) { return row.field_id; }));
          rows = supplied.filter(function (row) { return byId.has(row.field_id); }).map(function (row) { return Object.assign({}, byId.get(row.field_id), row); })
            .concat(data.fields.filter(function (field) { return !ids.has(field.field_id); }).map(function (field) { return Object.assign({}, field); }));
          draw();
        }
        function config() { return {columns:rows.map(function (row) {
          var value = {field_id:row.field_id, label:row.label, hidden:row.hidden === undefined ? !!row.default_hidden : row.hidden, wrap:row.wrap !== false};
          if (row.width !== undefined) value.width = row.width;
          return value;
        })}; }
        function draw() {
          table.textContent = ''; var header = el('tr'); ['列名','显示','宽度','换行','顺序'].forEach(function (text) { header.appendChild(el('th','',text)); }); table.appendChild(header);
          rows.forEach(function (row,index) {
            var tr = el('tr'); var title = document.createElement('input'); title.value = row.label; title.maxLength = 80; title.setAttribute('aria-label','列名：'+row.label); title.oninput = function () { row.label = title.value; };
            var visible = document.createElement('input'); visible.type = 'checkbox'; visible.checked = !(row.hidden === undefined ? row.default_hidden : row.hidden); visible.setAttribute('aria-label','显示：'+row.label); visible.onchange = function () { row.hidden = !visible.checked; };
            var width = document.createElement('input'); width.type = 'number'; width.min = 6; width.max = 120; width.value = row.width === undefined ? '' : row.width; width.placeholder = '默认'; width.style.width = '75px'; width.setAttribute('aria-label','宽度：'+row.label); width.oninput = function () { row.width = width.value === '' ? undefined : Number(width.value); };
            var wrap = document.createElement('input'); wrap.type = 'checkbox'; wrap.checked = row.wrap !== false; wrap.setAttribute('aria-label','换行：'+row.label); wrap.onchange = function () { row.wrap = wrap.checked; };
            [title,visible,width,wrap].forEach(function (input) { var td = el('td'); td.style.padding = '5px'; td.appendChild(input); tr.appendChild(td); });
            var order = el('td'); [-1,1].forEach(function (delta) { var move = btn(delta < 0 ? '上移' : '下移', function () { var other = index + delta; rows.splice(index,1); rows.splice(other,0,row); draw(); },'sr-btn'); move.disabled = index + delta < 0 || index + delta >= rows.length; move.setAttribute('aria-label',row.label+' '+move.textContent); order.appendChild(move); }); tr.appendChild(order); table.appendChild(tr);
          });
        }
        async function load(preferred, preserve) {
          data = await postView({action:'schemes',kind:'xlsx'});
          if (!dialog.isConnected) return;
          selector.textContent = ''; selector.appendChild(new Option('默认列设置',''));
          data.schemes.filter(function (scheme) { return !scheme.scope_folder_id || scheme.scope_folder_id === scope.value; }).forEach(function (scheme) { selector.appendChild(new Option((scheme.scope_folder_id ? '分类 · ' : '全局 · ') + scheme.name,scheme.scheme_id)); });
          var currentDefault = data.defaults.find(function (item) { return item.scope_folder_id === scope.value; }) || data.defaults.find(function (item) { return item.scope_folder_id === ''; });
          selector.value = preferred === undefined ? (currentDefault && currentDefault.scheme_id || '') : preferred;
          selected = data.schemes.find(function (scheme) { return scheme.scheme_id === selector.value; }) || null;
          name.value = selected ? selected.name : '我的文献视图';
          renderColumns(preserve || selected && selected.config);
        }
        async function run(action) { if (busy) return; busy = true; notice.textContent = '正在处理…'; try { await action(); if (notice.textContent === '正在处理…') notice.textContent = ''; } catch (error) { if (dialog.isConnected) notice.textContent = '未完成：'+userMessage(error); } finally { busy = false; } }
        async function save(apply) {
          var own = selected && selected.scope_folder_id === scope.value;
          var result = await postView({action:'scheme_save',kind:'xlsx',scope_folder_id:scope.value,name:name.value,config:config(),scheme_id:own ? selected.scheme_id : undefined,expected_revision:own ? selected.revision : 0});
          if (apply) await postView({action:'scheme_default',kind:'xlsx',scope_folder_id:scope.value,scheme_id:result.saved_scheme_id});
          await load(result.saved_scheme_id); notice.textContent = apply ? '已应用，刷新 Excel 后生效。' : '方案已保存。';
        }
        selector.onchange = function () { selected = data.schemes.find(function (scheme) { return scheme.scheme_id === selector.value; }) || null; name.value = selected ? selected.name : '我的文献视图'; renderColumns(selected && selected.config); };
        scope.onchange = function () { run(function () { return load(); }); };
        dialog.appendChild(btn('保存方案',function () { run(function () { return save(false); }); },'sr-btn'));
        dialog.appendChild(btn('保存并应用',function () { run(function () { return save(true); }); },'sr-btn sr-btn-primary'));
        dialog.appendChild(btn('恢复默认',function () { run(async function () { await postView({action:'scheme_default',kind:'xlsx',scope_folder_id:scope.value,scheme_id:null}); await load(); notice.textContent = scope.value ? '已恢复全库设置。' : '已恢复默认列。'; }); },'sr-btn'));
        dialog.appendChild(btn('刷新 Excel',function () { run(async function () { var result = await postView({action:'xlsx_refresh',scope_folder_id:scope.value}); notice.textContent = result.status === 'success' ? 'Excel 已更新，共 '+result.rows+' 篇。' : userMessage(result.error && result.error.detail || 'Excel 更新未完成，请重试。'); }); },'sr-btn'));
        var custom = el('section'); custom.appendChild(el('h3','','新增研究字段'));
        var fieldName = document.createElement('input'); fieldName.placeholder = '例如：研究设计、研究焦点'; fieldName.setAttribute('aria-label','新研究字段名称'); fieldName.maxLength = 80;
        var description = document.createElement('input'); description.placeholder = '填写说明（可选）'; description.setAttribute('aria-label','新研究字段说明'); description.maxLength = 2000;
        custom.append(fieldName,description,btn('创建字段',function () { run(async function () { var current = config(); await postView({action:'field_save',label:fieldName.value,description:description.value}); await load(selector.value,current); fieldName.value=''; description.value=''; notice.textContent='已创建，可在文献详情填写。'; }); },'sr-btn'));
        dialog.appendChild(custom);
        dialog.appendChild(btn('关闭',function () { dialog.close(); },'sr-btn'));
        dialog.addEventListener('close',function () { dialog.remove(); viewsDialog = null; });
        root.appendChild(dialog); dialog.showModal(); run(function () { return load(); });
      }
      function renderResearchFields(paperId, session) {
        var section = el('section','sr-research-fields'); controls.drawerBody.appendChild(section);
        function render(payload) {
          if (!drawerSessions.isCurrent(session,paperId)) return;
          section.textContent = ''; section.appendChild(el('h3','','研究字段'));
          if (!payload.fields.length) { section.appendChild(el('p','','可在 Excel 设置中添加字段。')); return; }
          payload.fields.forEach(function (field) {
            var value = payload.values.find(function (row) { return row.field_id === field.field_id; }) || {value:'',revision:0};
            var label = el('label','',field.label); var input = document.createElement('textarea'); input.value = value.value; input.maxLength = 32767; input.rows = 3; input.style.width = '100%'; input.setAttribute('aria-label',field.label); label.appendChild(input); section.appendChild(label);
            var source = value.origin === 'ai' ? 'AI（待核对）' + (value.source_matches_current ? '' : ' · 来源已变化') : '我的记录';
            section.appendChild(el('p','sr-muted',source + (field.description ? ' · '+field.description : '')));
            (value.evidence || []).forEach(function (entry) { var quote = el('blockquote','',entry.quote); if (entry.kind === 'abstract') quote.prepend(entry.language==='zh'?'中文摘要：':'英文摘要：'); else quote.appendChild(entryLink('原文第 '+entry.page+' 页','/sr/api/paper/'+encodeURIComponent(paperId)+'/pdf#page='+entry.page,true)); section.appendChild(quote); });
            var notice = el('span'); var save = btn('保存',async function () { save.disabled = true; try { var result = await postView({action:'value_set',paper_id:paperId,field_id:field.field_id,value:input.value,expected_revision:value.revision}); render(result); } catch (error) { if (drawerSessions.isCurrent(session,paperId)) notice.textContent='保存未完成：'+userMessage(error); } finally { save.disabled=false; } },'sr-btn'); section.append(save,notice);
          });
          section.appendChild(btn('向 AI 提问',function () { paperSessions.open(paperId).catch(function (error) { section.appendChild(el('p','','打开失败：'+userMessage(error))); }); },'sr-btn'));
        }
        postView({action:'values',paper_id:paperId}).then(render).catch(function (error) { if (drawerSessions.isCurrent(session,paperId)) section.textContent='研究字段暂不可用：'+userMessage(error); });
      }
      function openReaderEditor(paper) {
        var dialog = el('dialog','sr-dialog sr-reader-editor');
        dialog.style.width = '1180px';
        dialog.appendChild(el('h2','','阅读外观'));
        dialog.appendChild(el('p','','预览文献：'+paper.title));
        var notice = el('p'); notice.setAttribute('role','status'); dialog.appendChild(notice);
        var form = el('div','sr-form-grid'); dialog.appendChild(form);
        function input(label,values) {
          var wrapper=el('label','',label+' '), field=document.createElement(values ? 'select' : 'input'); field.setAttribute('aria-label',label);
          if(values) values.forEach(function(row){field.appendChild(new Option(row[1],row[0]));});
          wrapper.appendChild(field); form.appendChild(wrapper); return field;
        }
        var scope=input('适用范围',[['','全局']].concat(state.folders.map(function(row){return [row.folder_id,row.name];})));
        scope.value=paper.folder_id || '';
        var selector=input('已存方案',[]), name=input('方案名称'); name.maxLength=80;
        var theme='paper';
        dialog.appendChild(btn('主题设置',function(){dialog.close();dialog.remove();openSettings();},'sr-btn'));
        var font=input('正文字体',[['serif','衬线'],['sans','无衬线'],['mono','等宽']]);
        var size=input('正文字号'), width=input('正文宽度');
        size.type='number';size.min=14;size.max=26;width.type='number';width.min=640;width.max=1600;
        var layout=input('双语排版',[['original','英文，按段展开译文'],['interleaved','中英逐段'],['side_by_side','中英并排'],['chinese','中文正文']]);
        var template=el('textarea'), css=el('textarea');
        function templateField(label,field,extension) {
          var details=el('details'), summary=el('summary','',label);details.appendChild(summary);
          field.setAttribute('aria-label',label);field.rows=5;field.maxLength=64000;field.style.cssText='width:100%;font:13px monospace';
          var upload=document.createElement('input');upload.type='file';upload.accept=extension;upload.setAttribute('aria-label','导入'+label);
          upload.onchange=async function(){try{var file=upload.files[0];if(!file)return;if(file.size>128000)throw new Error('模板文件过大');field.value=await file.text();invalidate();notice.textContent='已导入，请预览。';}catch(error){notice.textContent=userMessage(error);}};
          details.append(upload,field);dialog.appendChild(details);
        }
        template.placeholder='保留 {{content}} 作为正文位置';
        templateField('HTML 模板',template,'.html,.htm');templateField('CSS 样式',css,'.css');
        var actions=el('div');actions.style.cssText='display:flex;gap:8px;margin:12px 0;flex-wrap:wrap';dialog.appendChild(actions);
        var preview=el('iframe');preview.title='阅读外观预览';preview.setAttribute('sandbox','allow-scripts');preview.style.cssText='width:100%;height:540px;border:1px solid var(--sr-line);border-radius:var(--sr-radius);background:var(--sr-bg)';dialog.appendChild(preview);
        var data=null,selected=null,busy=false,previewed='';
        function config(){return {theme:theme,font:font.value,font_size:Number(size.value),width:Number(width.value),layout:layout.value,html_template:template.value,css:css.value};}
        function invalidate(){previewed='';apply.disabled=true;save.disabled=true;}
        [font,size,width,layout,template,css].forEach(function(field){field.addEventListener('input',invalidate);});
        function display(value){theme=value.theme;font.value=value.font;size.value=value.font_size;width.value=value.width;layout.value=value.layout;template.value=value.html_template;css.value=value.css;invalidate();}
        async function run(task){if(busy)return;busy=true;notice.textContent='正在处理…';try{await task();}catch(error){notice.textContent='外观未更新：'+userMessage(error);}finally{busy=false;}}
        function choose(){selected=data.schemes.find(function(row){return row.scheme_id===selector.value;})||null;name.value=selected ? selected.name : '我的阅读方案';display(selected ? selected.config : data.builtin);}
        async function load(preferred){var results=await Promise.all([postView({action:'schemes',kind:'reader'}),postView({action:'reader_effective',paper_id:paper.paper_id})]);if(!dialog.isConnected)return;data=results[0];data.builtin={theme:'paper',font:'serif',font_size:18,width:1020,layout:'original',html_template:'{{content}}',css:''};selector.textContent='';selector.appendChild(new Option('默认外观',''));data.schemes.filter(function(row){return !row.scope_folder_id||row.scope_folder_id===scope.value;}).forEach(function(row){selector.appendChild(new Option((row.scope_folder_id?'分类 · ':'全局 · ')+row.name,row.scheme_id));});selector.value=preferred===undefined ? results[1].scheme_id||'' : preferred;choose();notice.textContent='预览后可保存。';}
        async function saveScheme(useDefault){if(previewed!==JSON.stringify(config()))throw new Error('请先预览当前设置');var own=selected&&selected.scope_folder_id===scope.value;var result=await postView({action:'scheme_save',kind:'reader',scope_folder_id:scope.value,name:name.value,config:config(),scheme_id:own?selected.scheme_id:undefined,expected_revision:own?selected.revision:0});if(useDefault)await postView({action:'scheme_default',kind:'reader',scope_folder_id:scope.value,scheme_id:result.saved_scheme_id});await load(result.saved_scheme_id);notice.textContent=useDefault?'已应用，重新打开阅读页后生效。':'方案已保存。';}
        actions.appendChild(btn('预览',function(){run(async function(){var value=config(),signature=JSON.stringify(value);var result=await postView({action:'reader_render',paper_id:paper.paper_id,config:value});if(!dialog.isConnected)return;preview.srcdoc=result.html;if(signature===JSON.stringify(config())){previewed=signature;save.disabled=false;apply.disabled=false;notice.textContent='预览已更新。';}else notice.textContent='设置已变化，请重新预览。';});},'sr-btn'));
        var save=btn('保存方案',function(){run(function(){return saveScheme(false);});},'sr-btn');save.disabled=true;
        var apply=btn('保存并应用',function(){run(function(){return saveScheme(true);});},'sr-btn sr-btn-primary');apply.disabled=true;actions.append(save,apply);
        actions.appendChild(btn('恢复默认',function(){run(async function(){await postView({action:'scheme_default',kind:'reader',scope_folder_id:scope.value,scheme_id:null});await load();notice.textContent=scope.value?'已恢复全库外观。':'已恢复默认外观。';});},'sr-btn'));
        actions.appendChild(entryLink('打开阅读页','/sr/reader/'+encodeURIComponent(paper.paper_id),true));
        actions.appendChild(btn('关闭',function(){dialog.close();},'sr-btn'));
        selector.onchange=choose;scope.onchange=function(){run(function(){return load('');});};
        dialog.addEventListener('close',function(){dialog.remove();});root.appendChild(dialog);dialog.showModal();run(function(){return load();});
      }
      function openLegacyHistory() {
        var dialog=el('dialog','sr-dialog sr-legacy-dialog');dialog.style.width='1000px';
        dialog.appendChild(el('h2','','历史对话'));dialog.appendChild(el('p','','历史对话只读，可能涉及多篇论文。继续提问请打开对应文献。'));
        var selector=el('select');selector.setAttribute('aria-label','旧会话');selector.style.maxWidth='100%';dialog.appendChild(selector);
        var notice=el('p');notice.setAttribute('role','status');dialog.appendChild(notice);
        var text=el('pre');text.style.cssText='white-space:pre-wrap;overflow-wrap:anywhere;font:15px/1.8 var(--sr-font-ui)';dialog.appendChild(text);
        var busy=false,page=null;
        function post(action,body){return api('/sr/api/chats/'+action,{method:'POST',headers:{'Content-Type':'application/json','x-sr-csrf':'1'},body:JSON.stringify(body||{})});}
        async function read(cursor){if(busy||!selector.value)return;busy=true;notice.textContent='正在读取…';try{var result=await post('legacy-read',Object.assign({session_id:selector.value},cursor||{}));if(!dialog.isConnected)return;page=result;text.textContent=result.text||'这一页没有可见消息。';notice.textContent=result.truncated?'还有更多消息，可继续翻页。':'已显示本页全部消息。';more.disabled=result.nextTextOffset===null;older.disabled=result.nextTextOffset!==null||result.nextBeforeSeq===null;}catch(error){notice.textContent='历史暂不可用：'+userMessage(error);}finally{busy=false;}}
        var more=btn('继续本页内容',function(){read({beforeSeq:page.beforeSeq,textOffset:page.nextTextOffset,pageSha256:page.pageSha256});},'sr-btn');more.disabled=true;
        var older=btn('读取更早消息',function(){read({beforeSeq:page.nextBeforeSeq});},'sr-btn');older.disabled=true;
        dialog.append(more,older,btn('关闭',function(){dialog.close();},'sr-btn'));selector.onchange=function(){read();};
        dialog.addEventListener('close',function(){dialog.remove();});root.appendChild(dialog);dialog.showModal();
        post('legacy').then(function(result){if(!dialog.isConnected)return;var rows=result.sessions.concat(result.reviews||[]);rows.forEach(function(row){selector.appendChild(new Option(row.label,row.session_id));});if(rows.length)read();else notice.textContent='暂无历史对话。';}).catch(function(error){notice.textContent=userMessage(error);});
      }
      function openRadar() {
        var dialog=el('dialog','sr-dialog sr-radar-dialog');dialog.style.width='1160px';
        dialog.appendChild(el('h2','','文献雷达'));
        dialog.appendChild(el('p','','确认研究方向后开始检索。候选文献由你选择纳入文献库。'));
        var notice=el('p');notice.setAttribute('role','status');dialog.appendChild(notice);
        var top=el('div');top.style.cssText='display:flex;gap:10px;flex-wrap:wrap';dialog.appendChild(top);
        var selector=el('select');selector.setAttribute('aria-label','研究方向');top.appendChild(selector);
        var editor=el('details');editor.open=true;editor.appendChild(el('summary','','方向配置与确认'));dialog.appendChild(editor);
        var grid=el('div','sr-form-grid');editor.appendChild(grid);
        function field(label,area){var wrapper=el('label','',label),control=el(area?'textarea':'input');control.setAttribute('aria-label',label);control.style.cssText='display:block;width:100%;box-sizing:border-box;padding:7px';if(area)control.rows=3;wrapper.appendChild(control);grid.appendChild(wrapper);return control;}
        var name=field('方向名称'),question=field('研究问题',true),goal=field('研究目标',true);
        name.maxLength=80;question.maxLength=2000;goal.maxLength=2000;
        var focus=field('检索概念与同义词',true);focus.placeholder='每行一个概念，同义词用 | 分隔，例如：\nantiphospholipid | APS\nsingle cell | single-cell';
        var inclusion=field('纳入范围',true),exclusion=field('排除范围',true),types=field('关注的研究类型',true),counter=field('相反结果关键词',true);
        [inclusion,exclusion,types,counter].forEach(function(control){control.placeholder='每行一项，可留空';});
        var crossref=field('Crossref 关键词（可选）');crossref.placeholder='留空则使用上方关键词';crossref.maxLength=500;
        var since=field('近期研究起始日期');since.type='date';
        var interval=field('自动检索间隔（小时，0 为关闭）');interval.type='number';interval.min=0;interval.max=8760;
        var size=field('每条查询数量上限');size.type='number';size.min=5;size.max=100;
        var sourceBox=el('fieldset');sourceBox.appendChild(el('legend','','检索来源'));var sources={};[['europe_pmc','Europe PMC'],['crossref','Crossref']].forEach(function(row){var label=el('label','',row[1]),check=el('input');check.type='checkbox';check.checked=true;check.setAttribute('aria-label',row[1]);sources[row[0]]=check;label.prepend(check);sourceBox.appendChild(label);});grid.appendChild(sourceBox);
        var classicLabel=el('label','','包含较早研究');var classics=el('input');classics.type='checkbox';classics.checked=true;classicLabel.prepend(classics);grid.appendChild(classicLabel);
        var seeds=el('select');seeds.multiple=true;seeds.size=4;seeds.setAttribute('aria-label','参考论文');var seedLabel=el('label','','参考论文');seedLabel.appendChild(seeds);grid.appendChild(seedLabel);
        var preview=el('div','sr-query-preview');editor.appendChild(preview);
        var confirmLabel=el('label','','已核对研究方向、查询词和检索频率');var consent=el('input');consent.type='checkbox';confirmLabel.prepend(consent);editor.appendChild(confirmLabel);
        var controls=el('div');controls.style.cssText='display:flex;gap:8px;flex-wrap:wrap;margin:14px 0';editor.appendChild(controls);
        var scanControls=el('div');scanControls.style.cssText='display:flex;gap:8px;flex-wrap:wrap;margin:14px 0';dialog.appendChild(scanControls);
        var listing=el('section');dialog.appendChild(listing);
        var data=null,current=null,busy=false,offset=0,dirty=true;
        function lines(value){return value.split(/\n|；|;/).map(function(row){return row.trim();}).filter(Boolean);}
        function config(){return {question:question.value,goal:goal.value,focus_groups:lines(focus.value).map(function(row){return row.split('|').map(function(term){return term.trim();}).filter(Boolean);}),crossref_query:crossref.value,
          inclusion:lines(inclusion.value),exclusion:lines(exclusion.value),research_types:lines(types.value),counter_terms:lines(counter.value),recent_since:since.value,include_classics:classics.checked,
          interval_hours:Number(interval.value),page_size:Number(size.value),sources:Object.keys(sources).filter(function(key){return sources[key].checked;}),seed_paper_ids:Array.from(seeds.selectedOptions).map(function(option){return option.value;})};}
        function post(body){return api('/sr/api/radar',{method:'POST',headers:{'Content-Type':'application/json','x-sr-csrf':'1'},body:JSON.stringify(body)});}
        function buttons(){confirm.disabled=!current||current.status!=='draft'||dirty||!consent.checked;var ready=current&&current.confirmed_revision===current.revision;scan.disabled=!ready;incremental.disabled=!ready;pause.disabled=!ready;pause.textContent=current&&current.status==='paused'?'恢复定期扫描':'暂停定期扫描';}
        function markDirty(){dirty=true;consent.checked=false;buttons();}
        grid.addEventListener('input',markDirty);grid.addEventListener('change',markDirty);consent.onchange=buttons;
        async function run(task){if(busy)return;busy=true;notice.textContent='正在处理…';try{await task();}catch(error){notice.textContent='未完成：'+userMessage(error);}finally{busy=false;buttons();}}
        function setForm(direction){
          current=direction;var value=direction?direction.config:{question:'',goal:'',focus_groups:[],inclusion:[],exclusion:[],research_types:[],seed_paper_ids:selections.values(),sources:['europe_pmc','crossref'],recent_since:new Date(Date.now()-730*86400000).toISOString().slice(0,10),include_classics:true,counter_terms:['no association','no effect','negative','contradictory'],interval_hours:0,page_size:20};
          name.value=direction?direction.name:'';question.value=value.question;goal.value=value.goal;focus.value=value.focus_groups.map(function(group){return group.join(' | ');}).join('\n');crossref.value=value.crossref_query||'';
          inclusion.value=value.inclusion.join('\n');exclusion.value=value.exclusion.join('\n');types.value=value.research_types.join('\n');counter.value=value.counter_terms.join('\n');since.value=value.recent_since;interval.value=value.interval_hours;size.value=value.page_size;classics.checked=value.include_classics;
          Object.keys(sources).forEach(function(key){sources[key].checked=value.sources.includes(key);});seeds.textContent='';var papers=new Map(state.items.map(function(paper){return [paper.paper_id,paper];}));(direction&&direction.seed_context||[]).forEach(function(paper){papers.set(paper.paper_id,paper);});value.seed_paper_ids.forEach(function(id){if(!papers.has(id))papers.set(id,{paper_id:id,title:'已选论文（标题暂不可用）'});});papers.forEach(function(paper){var option=new Option(paper.title,paper.paper_id);option.selected=value.seed_paper_ids.includes(paper.paper_id);seeds.appendChild(option);});
          dirty=!direction;consent.checked=false;preview.textContent=direction?'状态：'+({draft:'草稿，尚未确认',confirmed:'已确认',paused:'定期扫描已暂停'}[direction.status]||direction.status)+'；下次扫描：'+(direction.next_scan_at?new Date(direction.next_scan_at).toLocaleString():'仅按需'):'填写方向后保存草稿，核对将发送的查询。';buttons();
        }
        async function load(preferred){data=await post({action:'list'});if(!dialog.isConnected)return;selector.textContent='';selector.appendChild(new Option('新方向',''));data.directions.forEach(function(direction){selector.appendChild(new Option(direction.name,direction.direction_id));});selector.value=preferred||'';setForm(data.directions.find(function(row){return row.direction_id===selector.value;})||null);if(current)await candidates();else listing.textContent='尚未选择已保存方向。';notice.textContent=data.scheduler&&data.scheduler.error?'定期扫描暂不可用：'+userMessage(data.scheduler.error):'修改方向后需重新确认。';}
        async function candidates(){var result=await post({action:'candidates',direction_id:current.direction_id,offset:offset,limit:20});if(!dialog.isConnected)return;listing.textContent='';listing.appendChild(el('h3','','候选列表 · '+result.total+' 篇'));listing.appendChild(el('p','','根据摘要初筛，请结合原文判断。'));
          if(result.scans.length){var latest=result.scans[0],coverage=el('details');coverage.appendChild(el('summary','','最近检索：'+({completed:'完成',partial:'部分完成',failed:'失败',running:'进行中'}[latest.status]||'待查看')+' · '+new Date(latest.started_at).toLocaleString()));(latest.summary.coverage||[]).forEach(function(row){coverage.appendChild(el('p','',sourceLabel(row.source)+' · '+sourceLabel(row.lane)+'：返回 '+row.returned+' / 检索命中 '+row.total+(row.has_more?'；还有更多结果':'')));});(latest.summary.errors||[]).forEach(function(row){coverage.appendChild(el('p','','来源暂不可用：'+sourceLabel(row.source)+'。'+userMessage(row.detail)));});listing.appendChild(coverage);}
          result.candidates.forEach(function(candidate){var paper=candidate.metadata,card=el('article','sr-radar-candidate');card.appendChild(el('h4','',paper.title));
            card.appendChild(el('p','',((paper.authors||[]).slice(0,3).join('、')||'作者未报告')+' · '+(paper.year||'年份待核对')+' · '+(paper.journal||'期刊待核对')));
            var status={unreviewed:'待评估',relevant:'相关',irrelevant:'不相关',later:'稍后再读',admitted:'已纳入',in_library:'文献库已有'};
            card.appendChild(el('p','',status[candidate.state]+' · '+(paper.abstract_en?'有摘要':'暂无摘要')));
            var oa={metadata_indicates_oa:'标注为开放获取，PDF 待确认',open_license_hint_unverified:'开放获取待确认',unknown_or_non_oa:'开放获取待确认',unknown:'开放获取待确认'};card.appendChild(el('p','',oa[paper.oa_status]||'开放获取待确认'));
            if(paper.status_flags&&paper.status_flags.length)card.appendChild(el('p','','出版状态：'+paper.status_flags.map(publicationStatus).join('；')+'。请打开来源核对。'));
            if(paper.identity_conflict||paper.library_identity_conflict)card.appendChild(el('p','','文献编号不一致，请核对 DOI / PMID 后再纳入。'));
            if(isSafeHttpUrl(paper.source_url))card.appendChild(entryLink('出版来源',paper.source_url,true));
            var assessment=candidate.assessment,details=el('details');details.open=true;details.appendChild(el('summary','',(assessment.origin==='ai'?'AI 评估 · '+({relevant:'与方向相关',uncertain:'相关性未确定',not_relevant:'与方向不符'}[assessment.verdict]):'推荐理由')+(candidate.assessment_current?'':' · 已过期，请重新评估')));
            [['relevance','相关性'],['design','研究设计与证据'],['reading_value','阅读价值'],['timeliness','时效性']].forEach(function(pair){var item=assessment[pair[0]]||{};details.appendChild(el('p','',pair[1]+'：'+(item.reason||item.label||item.role||'待评估')));(item.evidence||[]).forEach(function(evidence){details.appendChild(el('blockquote','',evidence.quote+'（'+(sourceLabel(evidence.field)||'来源')+'）'));});if(item.exclusion_hints&&item.exclusion_hints.length)details.appendChild(el('p','','可能不符合纳入条件：'+item.exclusion_hints.join('、')));if(item.counterevidence_hints&&item.counterevidence_hints.length)details.appendChild(el('p','','可能涉及相反结果：'+item.counterevidence_hints.join('、')+'，需核对原意。'));});
            (assessment.limitations||[]).forEach(function(text){details.appendChild(el('p','',text));});card.appendChild(details);
            if(paper.abstract_en){var abstract=el('details');abstract.appendChild(el('summary','','摘要'));abstract.appendChild(el('p','',paper.abstract_en));card.appendChild(abstract);}
            var provenance=el('details');provenance.appendChild(el('summary','','检索记录'));candidate.discoveries.forEach(function(discovery){provenance.appendChild(el('p','',sourceLabel(discovery.source)+' · '+new Date(discovery.discovered_at).toLocaleString()+' · '+discovery.query.query));});card.appendChild(provenance);
            if(candidate.feedback.length)card.appendChild(el('p','','我的反馈：'+candidate.feedback.map(function(item){return (status[item.state]||item.state)+(item.reason?' · '+item.reason:'');}).join('；')));
            var actions=el('div');actions.style.cssText='display:flex;gap:8px;flex-wrap:wrap;align-items:center';card.appendChild(actions);
            if(candidate.library_paper_id)actions.appendChild(btn('打开文献对话',function(){paperSessions.open(candidate.library_paper_id).catch(function(error){notice.textContent=userMessage(error);});},'sr-btn'));
            else {var reason=el('input');reason.placeholder='反馈原因（可选）';reason.maxLength=2000;reason.setAttribute('aria-label','反馈原因：'+paper.title);actions.appendChild(reason);[['relevant','相关'],['irrelevant','不相关'],['later','稍后再读'],['unreviewed','恢复待评估']].forEach(function(pair){actions.appendChild(btn(pair[1],function(){run(async function(){await post({action:'feedback',direction_id:current.direction_id,candidate_id:candidate.candidate_id,state:pair[0],reason:reason.value});await candidates();notice.textContent='反馈已保存。';});},'sr-btn'));});
              var folder=el('select');folder.setAttribute('aria-label','纳入分类：'+paper.title);folder.appendChild(new Option('待归类',''));state.folders.forEach(function(row){folder.appendChild(new Option(row.name,row.folder_id));});actions.appendChild(folder);
              var admit=btn('纳入文献库',function(){run(async function(){var result=await post({action:'admit',direction_id:current.direction_id,candidate_id:candidate.candidate_id,metadata_sha:candidate.metadata_sha,folder_id:folder.value||null,confirmed:true});await candidates();loadLibrary();notice.textContent='已加入文献库。';});},'sr-btn sr-btn-primary');admit.disabled=!!(paper.identity_conflict||paper.library_identity_conflict);actions.appendChild(admit);
            }listing.appendChild(card);
          });
          var pagination=el('div'),back=btn('候选上一页',function(){offset=Math.max(0,offset-20);run(candidates);},'sr-btn'),next=btn('候选下一页',function(){offset=result.next_offset;run(candidates);},'sr-btn');back.disabled=offset===0;next.disabled=result.next_offset===null;pagination.append(back,el('span','','第 '+(Math.floor(offset/20)+1)+' 页'),next);listing.appendChild(pagination);
        }
        controls.appendChild(btn('保存并预览',function(){run(async function(){var result=await post({action:'draft',direction_id:current&&current.direction_id,expected_revision:current?current.revision:0,name:name.value,config:config()});await load(result.direction_id);setForm(result);preview.textContent='';preview.appendChild(el('p','','以下查询词将发送至所选文献来源。'));result.outbound_queries.forEach(function(query){preview.appendChild(el('p','',sourceLabel(query.source)+' · '+sourceLabel(query.lane)+'：'+query.query));});dirty=false;notice.textContent='已保存，请核对查询并确认方向。';});},'sr-btn'));
        var confirm=btn('确认研究方向',function(){run(async function(){if(!consent.checked||dirty)throw new Error('请先保存并核对方向');var result=await post({action:'confirm',direction_id:current.direction_id,expected_revision:current.revision,confirmed:true});await load(result.direction_id);editor.open=false;notice.textContent='方向已确认，可按需扫描。'+(result.config.interval_hours?'工作台运行时按所设频率增量扫描。':'当前仅按需扫描。');});},'sr-btn sr-btn-primary');controls.appendChild(confirm);
        var scan=btn('查找文献',function(){run(async function(){var result=await post({action:'scan',direction_id:current.direction_id,expected_revision:current.revision,mode:'discovery'});offset=0;await candidates();notice.textContent='扫描结束：'+result.new_candidate_ids.length+' 条新候选；请评估后决定是否纳入。';});},'sr-btn sr-btn-primary');
        var incremental=btn('查找新增文献',function(){run(async function(){var result=await post({action:'scan',direction_id:current.direction_id,expected_revision:current.revision,mode:'incremental'});await candidates();notice.textContent='增量扫描结束：'+result.new_candidate_ids.length+' 条新候选。未完成来源和分页范围见扫描记录。';});},'sr-btn');
        var pause=btn('暂停定期扫描',function(){run(async function(){current=await post({action:'pause',direction_id:current.direction_id,paused:current.status!=='paused'});buttons();notice.textContent=current.status==='paused'?'定期扫描已暂停，仍可手动扫描。':'已恢复确认方向的定期扫描。';});},'sr-btn');scanControls.append(scan,incremental,pause);
        scanControls.appendChild(btn('复制评估指令',function(){run(async function(){if(!current)throw new Error('请先保存方向');await navigator.clipboard.writeText('请评估文献雷达方向 '+current.direction_id+' 的候选。先读取方向、种子论文和候选来源，再按相关性、研究设计、阅读价值与时效性给出有短引文依据的评估，说明摘要初筛限制；兼顾经典、新进展和相反结果。不要替我确认方向或纳入文献。');notice.textContent='已复制，请粘贴到 Codex 或工作台主对话中。';});},'sr-btn'));
        top.appendChild(btn('新建方向',function(){selector.value='';setForm(null);listing.textContent='';editor.open=true;},'sr-btn'));
        top.appendChild(btn('关闭',function(){dialog.close();},'sr-btn'));
        selector.onchange=function(){offset=0;run(function(){return load(selector.value);});};dialog.addEventListener('close',function(){dialog.remove();});root.appendChild(dialog);dialog.showModal();run(function(){return load();});
      }

      function createQueryStore(onChange) {
        var query = { page: 1, page_size: 50, q: '', folder: '', tags: '', status: '', recent_days: '' };
        return {
          get: function () { return Object.assign({}, query); },
          set: function (patch, resetPage) {
            query = Object.assign({}, query, patch);
            query.page_size = Math.min(100, Math.max(1, Number(query.page_size) || 50));
            if (resetPage) query.page = 1;
            updateNavigationSelection();
            onChange();
          },
        };
      }

      function libraryUrl(query) {
        var params = new URLSearchParams();
        Object.keys(query).forEach(function (key) {
          if (query[key] !== '') params.set(key, String(query[key]));
        });
        return '/sr/api/library?' + params.toString();
      }

      function updateNavigationSelection() {
        var folder = queryStore.get().folder;
        controls.navigation.forEach(function (item) {
          item.node.setAttribute('aria-current', String(item.folderId === folder));
        });
      }

      function updatePagination() {
        var query = queryStore.get();
        controls.pageLabel.textContent = '第 ' + query.page + ' 页 · 共 ' + state.total + ' 篇';
        controls.prev.disabled = state.status !== 'ready' || query.page <= 1;
        controls.next.disabled = state.status !== 'ready' || query.page * query.page_size >= state.total;
      }

      function entryButton(model, onClick) {
        var button = btn(model.label, onClick || function () {}, 'sr-entry');
        if (model.disabledReason) { button.disabled = true; button.title = model.disabledReason; button.setAttribute('aria-label', model.label + '：' + model.disabledReason); }
        return button;
      }
      function entryLink(label, href, external) {
        var link = el('a', 'sr-entry', label); link.href = href;
        if (external) { link.target = '_blank'; link.rel = 'noopener'; }
        return link;
      }
      function runUiAction(promise, label, paperId) {
        return promise.catch(function (error) {
          if (error && error.name === 'AbortError') return;
          if (!disposed) patchPaper(paperId, { last_error: label + '失败：' + userMessage(error) });
        });
      }
      function closeDrawer(event) {
        if (event && event.type === 'click' && event.target !== controls.backdrop && event.currentTarget === controls.backdrop) return;
        lifecycle.closeDrawerScope(); controls.backdrop.hidden = true; controls.drawer.setAttribute('aria-hidden', 'true'); sidebar.inert = false; main.inert = false;
        if (drawerOpener && typeof drawerOpener.focus === 'function') drawerOpener.focus(); drawerOpener = null;
      }
      function renderDrawer(paper, payload, session) {
        if (!drawerSessions.isCurrent(session, paper.paper_id)) return;
        var item = payload.detail.item || payload.detail || {}; var abstract = payload.abstract || {};
        controls.drawerBody.textContent = '';
        controls.drawerBody.appendChild(el('h2', '', item.title || paper.title || '（无题名）'));
        renderResearchFields(paper.paper_id, session);
        controls.drawerBody.appendChild(btn('阅读外观',function(){openReaderEditor(paper);},'sr-btn'));
        var authors = Array.isArray(item.authors) ? item.authors.join('、') : paper.authors_short || '作者未知';
        controls.drawerBody.appendChild(el('p', 'sr-muted', authors + (item.year || paper.year ? ' · ' + (item.year || paper.year) : '') + (item.journal ? ' · ' + item.journal : '')));
        if (item.doi) controls.drawerBody.appendChild(el('p', 'sr-biblio', 'DOI：' + item.doi));
        if (item.pmid) controls.drawerBody.appendChild(el('p', 'sr-biblio', 'PMID：' + item.pmid));
        if (item.source_url) { var sourceLine = el('p', 'sr-biblio', '来源：'); if (isSafeHttpUrl(item.source_url)) sourceLine.appendChild(entryLink(item.source_url, item.source_url, true)); else sourceLine.appendChild(document.createTextNode(item.source_url)); controls.drawerBody.appendChild(sourceLine); }
        controls.drawerBody.appendChild(el('p', 'sr-biblio', '归类：' + (item.folder_name || paper.folder || '待归类') + '｜标签：' + ((item.tags || paper.tags || []).join('、') || '无')));
        var pairs = pairAbstractParagraphs(abstract.abstract_en, abstract.abstract_zh);
        controls.drawerBody.appendChild(el('h3', '', '摘要'));
        if (!pairs.length) controls.drawerBody.appendChild(el('p', 'sr-empty-note', '待补摘要'));
        pairs.forEach(function (pair) { var block = el('section', 'sr-abstract-pair'); if (pair.en) block.appendChild(el('p', 'sr-abstract-en', pair.en)); if (pair.zh) block.appendChild(el('p', 'sr-abstract-zh', pair.zh)); controls.drawerBody.appendChild(block); });
        controls.drawerBody.appendChild(el('p', 'sr-muted', '摘要：' + readingStatus(abstract.status || paper.abstract_status) + '｜全文：' + readingStatus(paper.full_read_status)));
        var failure = abstract.last_error || paper.last_error; if (failure) controls.drawerBody.appendChild(el('p', 'sr-error-note', userMessage(failure)));
        var links = el('div', 'sr-drawer-actions'); var model = paperEntryModel(paper, isSafeHttpUrl);
        if (paper.has_pdf) links.appendChild(entryLink('PDF', '/sr/api/paper/' + encodeURIComponent(paper.paper_id) + '/pdf', true));
        if (paper.has_reader) links.appendChild(entryLink('阅读 HTML', '/sr/reader/' + encodeURIComponent(paper.paper_id)));
        links.appendChild(btn('查看图表文件', function () { drawerActions.loadAssets(paper.paper_id, session); }, 'sr-entry'));
        links.appendChild(btn('整理文章图表', function () { exportPaperAssets(paper.paper_id, session); }, 'sr-entry'));
        var job = payload.detail.job || {}; var jobDetail = job.detail || {}; var needsPdf = (job.status === 'waiting_user' && jobDetail.reason_code === 'pdf_required') || (paper.needsUser && paper.pdfRequired);
        if (needsPdf) {
          var identifier = item.doi || item.pmid || item.source_url || '';
          var activeJobId = item.active_job_id || paper.active_job_id || '';
          var validActiveJob = /^job_[0-9a-f]{16}$/.test(activeJobId);
          var oaRetry = btn('重新获取 PDF', function () { drawerActions.oaDownload(paper.paper_id, activeJobId, identifier).then(function () { drawerSessions.guard(session, paper.paper_id, function () { closeDrawer(); refreshPaper(); }); }).catch(function (error) { drawerSessions.guard(session, paper.paper_id, function () { if (error.name !== 'AbortError') controls.drawerBody.appendChild(el('p', 'sr-error-note', 'PDF 获取失败：' + userMessage(error))); }); }); }, 'sr-entry');
          if (!identifier || !validActiveJob) { oaRetry.disabled = true; oaRetry.title = !validActiveJob ? '请重新开始全文阅读' : '缺少 DOI 或原文链接'; } links.appendChild(oaRetry);
          var uploadLabel = el('label', 'sr-entry', '添加本地 PDF'); var upload = document.createElement('input'); upload.type = 'file'; upload.accept = 'application/pdf,.pdf'; upload.hidden = true;
          if (!validActiveJob) { upload.disabled = true; uploadLabel.title = '请重新开始全文阅读'; uploadLabel.setAttribute('aria-disabled', 'true'); }
          upload.addEventListener('change', function () { var file = upload.files && upload.files[0]; if (!file) return; var reader = new FileReader(); drawerSessions.trackReader(session, paper.paper_id, reader); reader.onload = function () { drawerSessions.guard(session, paper.paper_id, function () { drawerActions.attachPdf(paper.paper_id, activeJobId, String(reader.result).split(',').pop()).then(function () { drawerSessions.guard(session, paper.paper_id, function () { closeDrawer(); refreshPaper(); }); }).catch(function (error) { drawerSessions.guard(session, paper.paper_id, function () { if (error.name !== 'AbortError') controls.drawerBody.appendChild(el('p', 'sr-error-note', '添加 PDF 失败：' + userMessage(error))); }); }); }); }; reader.onloadend = function () { drawerSessions.releaseReader(reader); }; reader.onerror = function () { drawerSessions.releaseReader(reader); drawerSessions.guard(session, paper.paper_id, function () { controls.drawerBody.appendChild(el('p', 'sr-error-note', '读取 PDF 失败')); }); }; reader.onabort = function () { drawerSessions.releaseReader(reader); }; reader.readAsDataURL(file); });
          uploadLabel.appendChild(upload); links.appendChild(uploadLabel);
        }
        controls.drawerBody.appendChild(links);
      }
      function openDrawer(paper, opener, options) {
        lifecycle.closeDrawerScope(); var session = drawerSessions.open(paper.paper_id); drawerOpener = opener; controls.backdrop.hidden = false; controls.drawer.setAttribute('aria-hidden', 'false'); sidebar.inert = true; main.inert = true; controls.drawerBody.textContent = '正在加载详情…'; controls.drawerClose.focus();
        drawerActions.loadDetail(paper.paper_id).then(function (payload) { drawerSessions.guard(session, paper.paper_id, function () { renderDrawer(paper, payload, session); if (options && options.exportAfter) exportPaperAssets(paper.paper_id, session); }); }).catch(function (error) { drawerSessions.guard(session, paper.paper_id, function () { if (error.name !== 'AbortError') controls.drawerBody.textContent = '详情加载失败：' + userMessage(error); }); });
      }
      function patchPaper(paperId, patch) {
        state.items = state.items.map(function (paper) { return paper.paper_id === paperId ? Object.assign({}, paper, patch) : paper; }); renderNavigationList();
      }
      function refreshPaper() { loadLibrary(); }
      function showExportAssets(paperId, assets, session) {
        if (!drawerSessions.isCurrent(session, paperId)) return;
        var count = '图片 ' + (Number(assets.figures) || 0) + ' · 表格 ' + (Number(assets.tables) || 0);
        var result = el('div', 'sr-export-result', count); result.appendChild(el('code', '', assets.exports_path || ''));
        if (assets.exports_path && navigator.clipboard) result.appendChild(btn('复制文件位置', function () { navigator.clipboard.writeText(assets.exports_path); }, 'sr-entry'));
        controls.drawerBody.appendChild(result);
      }
      function showExportError(paperId, message, session) { if (drawerSessions.isCurrent(session, paperId)) controls.drawerBody.appendChild(el('p', 'sr-error-note', message === '尚未整理' ? '图表尚未整理' : '图表整理失败：' + userMessage(message))); }
      function exportPaperAssets(paperId, session) {
        drawerActions.exportAssets(paperId, session).catch(function (error) { if (error.name !== 'AbortError') showExportError(paperId, error.message, session); });
      }

      function listMessage(text, cls, retry) {
        var message = el('div', cls || 'sr-empty');
        message.appendChild(el('span', '', text));
        if (retry) message.appendChild(btn('重试', loadLibrary, 'sr-btn sr-retry'));
        return message;
      }

      function requestDownloads(paperIds) {
        if (!paperIds.length) return Promise.resolve();
        controls.batchNotice.textContent = 'PDF 获取任务已在后台排队。';
        return api('/sr/api/download-batch', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ selection: paperIds }) })
          .then(function (result) {
            controls.batchNotice.textContent = '已提交 ' + paperIds.length + ' 篇 PDF 获取任务' + '。';
            selections.clear(); renderBatchToolbar();
            return result;
          }).catch(function (error) { controls.batchNotice.textContent = 'PDF 获取失败：' + userMessage(error); });
      }

      function locateExcel(paperId) {
        controls.batchNotice.textContent = '正在定位 Excel 记录…';
        return api('/sr/api/excel/locate?paper_id=' + encodeURIComponent(paperId), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
          .then(function (result) { controls.batchNotice.textContent = result.selected ? '已在 Excel 总表中定位该文献。' : '已打开文献总表，请按论文名查找对应记录。'; })
          .catch(function (error) { controls.batchNotice.textContent = '定位 Excel 失败：' + userMessage(error); });
      }

      function renderPaperRow(paper) {
        var row = el('article', 'sr-paper-row');
        var selectWrap = el('div', 'sr-paper-select');
        var checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.checked = selections.values().includes(paper.paper_id); checkbox.setAttribute('aria-label', '选择 ' + (paper.title || '无题名文献'));
        checkbox.addEventListener('change', function () { selections.toggle(paper.paper_id, checkbox.checked); renderBatchToolbar(); });
        selectWrap.appendChild(checkbox); row.appendChild(selectWrap);

        var content = el('div', 'sr-paper-content');
        var title = btn(paper.title || '（无题名）', function () { openDrawer(paper, title); }, 'sr-paper-title sr-link-button'); title.title = paper.title || '（无题名）'; content.appendChild(title);
        var meta = el('div', 'sr-paper-meta');
        meta.appendChild(el('span', '', paper.authors_short || '作者未知'));
        if (paper.year) meta.appendChild(el('span', '', String(paper.year)));
        if (paper.journal) meta.appendChild(el('span', '', paper.journal));
        if (paper.folder && !queryStore.get().folder) meta.appendChild(el('span', 'sr-folder-chip', paper.folder));
        (paper.tags || []).slice(0, 3).forEach(function (tag) { meta.appendChild(el('span', 'sr-tag', tag)); });
        if ((paper.tags || []).length > 3) meta.appendChild(el('span', 'sr-tag-more', '+' + ((paper.tags || []).length - 3)));
        if (paper.last_error) meta.appendChild(el('span', 'sr-row-failure', '处理失败'));
        else if (['queued', 'running', '获取 PDF', '解析全文', '翻译与生成'].includes(paper.full_read_status)) meta.appendChild(el('span', 'sr-row-running', '处理中'));
        content.appendChild(meta);
        var searchMatches = renderSearchMatches(paper); if (searchMatches) content.appendChild(searchMatches);
        row.appendChild(content);

        var actions = el('div', 'sr-row-actions'); var model = paperEntryModel(paper, isSafeHttpUrl);
        if (model.pdf.href) actions.appendChild(entryLink(model.pdf.label, model.pdf.href + encodeURIComponent(paper.paper_id) + '/pdf', model.pdf.external));
        else actions.appendChild(entryButton(model.pdf, function () { requestDownloads([paper.paper_id]); }));
        if (model.html.href) actions.appendChild(entryLink(model.html.label, model.html.href + encodeURIComponent(paper.paper_id)));
        else actions.appendChild(entryButton(model.html));
        var reviewButton = entryButton({ label: '文献对话' }, function () {
          reviewButton.disabled = true;
          controls.batchNotice.textContent = '正在打开对话…';
          paperSessions.open(paper.paper_id).then(function () {
            controls.batchNotice.textContent = '已打开“' + (paper.title || '无题名文献') + '”的对话。';
          }).catch(function (error) {
            controls.batchNotice.textContent = '对话打开失败：' + userMessage(error);
          }).finally(function () { if (!disposed) reviewButton.disabled = false; });
        });
        actions.appendChild(reviewButton);
        actions.appendChild(entryButton(model.excel, function () { locateExcel(paper.paper_id); }));
        row.appendChild(actions);
        return row;
      }

      function renderNavigationList() {
        if (disposed) return;
        updatePagination();
        controls.paperList.textContent = '';
        if (state.status === 'loading') { controls.paperList.appendChild(listMessage('正在加载文献…')); return; }
        if (state.status === 'error') { controls.paperList.appendChild(listMessage('加载失败：' + userMessage(state.error), 'sr-error', true)); return; }
        if (!state.items.length) { controls.paperList.appendChild(listMessage('没有符合条件的文献')); return; }
        state.items.forEach(function (paper) { controls.paperList.appendChild(renderPaperRow(paper)); });
      }

      function loadLibrary() {
        if (disposed) return Promise.resolve();
        if (request) request.abort();
        request = new AbortController();
        var sequence = ++requestSequence;
        state.status = 'loading';
        renderNavigationList();
        return api(libraryUrl(queryStore.get()), { signal: request.signal }).then(function (data) {
          if (disposed || sequence !== requestSequence) return;
          state.items = data.items || [];
          state.total = Number(data.total) || 0;
          state.status = 'ready';
          renderNavigationList();
        }).catch(function (error) {
          if (disposed || sequence !== requestSequence || error.name === 'AbortError') return;
          state.status = 'error';
          state.error = error.message;
          renderNavigationList();
        });
      }

      function addNavigationItem(parent, icon, label, folderId) {
        var item = btn('', function () { queryStore.set({ folder: folderId }, true); }, 'sr-nav-item');
        item.appendChild(el('span', '', icon));
        item.appendChild(el('span', 'sr-nav-label', label));
        controls.navigation.push({ node: item, folderId: folderId });
        parent.appendChild(item);
        updateNavigationSelection();
      }

      function filterSelect(label, values, key) {
        var wrap = el('label', 'sr-filter');
        wrap.appendChild(el('span', '', label));
        var select = document.createElement('select');
        values.forEach(function (entry) {
          var option = el('option', '', entry[0]); option.value = entry[1]; select.appendChild(option);
        });
        select.addEventListener('change', function () { var patch = {}; patch[key] = select.value; queryStore.set(patch, true); });
        wrap.appendChild(select);
        return wrap;
      }

      function updateIngestSubmit() {
        var titles = normalizeIngestTitles(controls.ingestInput.value, ingestMode === 'batch');
        controls.ingestSubmit.disabled = ingestSubmitting || !titles.length;
      }
      function closeIngestDialog() {
        if (ingestSubmitting) return;
        controls.ingestBackdrop.hidden = true;
        controls.ingestDialog.setAttribute('aria-hidden', 'true');
        sidebar.inert = false; main.inert = false;
        if (ingestOpener && typeof ingestOpener.focus === 'function') ingestOpener.focus();
        ingestOpener = null;
      }
      function openIngestDialog(mode, opener) {
        ingestMode = mode;
        ingestOpener = opener;
        controls.ingestTitle.textContent = mode === 'batch' ? '批量粘贴文献' : '添加文献';
        controls.ingestHint.textContent = mode === 'batch' ? '每行输入一篇文献题名。' : '输入一篇文献的题名。';
        controls.ingestInput.value = '';
        controls.ingestInput.rows = mode === 'batch' ? 9 : 3;
        controls.ingestStatus.textContent = '';
        controls.ingestBackdrop.hidden = false;
        controls.ingestDialog.setAttribute('aria-hidden', 'false');
        controls.ingestDialog.setAttribute('aria-label', mode === 'batch' ? '批量粘贴文献' : '添加文献');
        sidebar.inert = true; main.inert = true;
        updateIngestSubmit();
        controls.ingestInput.focus();
      }
      function submitIngest(event) {
        event.preventDefault();
        var titles = normalizeIngestTitles(controls.ingestInput.value, ingestMode === 'batch');
        if (!titles.length || ingestSubmitting) { updateIngestSubmit(); return; }
        ingestSubmitting = true;
        ingestRequest = new AbortController();
        controls.ingestCancel.disabled = ingestSubmitting;
        controls.ingestStatus.textContent = '正在录入 0 / ' + titles.length + '…';
        updateIngestSubmit();
        var succeeded = 0; var failed = 0;
        var chain = Promise.resolve();
        titles.forEach(function (title, index) {
          chain = chain.then(function () {
            controls.ingestStatus.textContent = '正在录入 ' + (index + 1) + ' / ' + titles.length + '…';
            return api('/sr/api/library', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: title }), signal: ingestRequest.signal })
              .then(function () { succeeded += 1; })
              .catch(function (error) { if (error.name === 'AbortError') throw error; failed += 1; });
          });
        });
        chain.then(function () {
          if (disposed) return;
          controls.ingestStatus.textContent = failed ? '录入成功 ' + succeeded + ' 篇，录入失败 ' + failed + ' 篇。' : '添加成功 ' + succeeded + ' 篇。';
          if (succeeded) loadLibrary();
        }).catch(function (error) {
          if (!disposed && error.name !== 'AbortError') controls.ingestStatus.textContent = '添加失败：' + userMessage(error);
        }).finally(function () {
          ingestSubmitting = false;
          ingestRequest = null;
          controls.ingestCancel.disabled = false;
          updateIngestSubmit();
        });
      }

      var queryStore = createQueryStore(loadLibrary);
      var selections = createSelectionStore();
      var drawerActions = createPaperActionController({ api: api, onPatch: patchPaper, onRefresh: refreshPaper, onAssets: showExportAssets, onAssetsError: showExportError });
      var rowActions = createPaperActionController({ api: api, onPatch: patchPaper, onRefresh: refreshPaper });
      var batchActions = createBatchController({ selection: selections, api: api, onSummary: function (message) { controls.batchNotice.textContent = message; renderBatchToolbar(); loadLibrary(); } });
      var lifecycle = createLiteratureLifecycle(drawerSessions, drawerActions, rowActions);
      controls.navigation = [];
      var root = el('div', 'sr-root');
      root.style.cssText = '--sr-highlight-yellow:#ffd43b;--sr-highlight-blue:#2b9cf0;--sr-sidebar-width:240px;--sr-sidebar-width-collapsed:56px';
      function themeChanged(event) { if(!disposed) applyTheme(root,event.detail); }
      window.addEventListener('sr-theme-change',themeChanged);
      postView({action:'theme_get'}).then(function(theme){if(!disposed)applyTheme(root,theme);}).catch(function(){});
      var style = document.createElement('style');
      style.textContent = '.sr-root{position:relative;display:grid;grid-template-columns:var(--sr-sidebar-width) minmax(0,1fr);height:100%;min-width:0;min-height:720px;background:var(--sr-bg);color:var(--sr-text);font:13px/1.45 Inter,"Noto Sans SC",sans-serif;overflow:hidden}.sr-root.sr-collapsed{grid-template-columns:var(--sr-sidebar-width-collapsed) minmax(0,1fr)}.sr-sidebar{border-right:1px solid var(--sr-line);padding:18px 12px;background:#eeece5;overflow:hidden}.sr-sidebar-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:22px}.sr-brand{font:700 15px/1.2 Georgia,"Noto Serif SC",serif;letter-spacing:.08em}.sr-collapsed .sr-brand,.sr-collapsed .sr-nav-label,.sr-collapsed .sr-folder-list{display:none}.sr-toggle,.sr-btn,.sr-nav-item{border:1px solid var(--sr-line);background:var(--sr-surface);color:var(--sr-text);border-radius:6px;cursor:pointer}.sr-toggle{width:32px;height:32px}.sr-nav-item{display:flex;width:100%;gap:9px;padding:8px;margin:4px 0;text-align:left}.sr-nav-item[aria-current=true]{border-color:var(--sr-accent);box-shadow:inset 3px 0 var(--sr-highlight-yellow);color:var(--sr-accent)}.sr-folder-title{margin:20px 8px 8px;color:var(--sr-muted);font-size:11px;letter-spacing:.12em}.sr-folder-list{display:flex;flex-direction:column}.sr-main{display:flex;flex-direction:column;min-width:0;padding:22px 24px}.sr-toolbar{display:flex;align-items:end;gap:8px;flex-wrap:wrap;padding-bottom:14px;border-bottom:1px solid var(--sr-line)}.sr-toolbar[hidden]{display:none}.sr-search{flex:1 1 300px;min-width:220px}.sr-search input,.sr-filter input,.sr-filter select{box-sizing:border-box;width:100%;height:34px;border:1px solid var(--sr-line);border-radius:6px;background:var(--sr-surface);color:var(--sr-text);padding:0 10px}.sr-filter{display:flex;flex-direction:column;gap:3px;color:var(--sr-muted);font-size:11px}.sr-btn{height:34px;padding:0 12px}.sr-btn-primary{background:var(--sr-text);color:var(--sr-surface);border-color:var(--sr-text)}.sr-btn-mark{box-shadow:inset 0 -3px var(--sr-highlight-blue)}.sr-paper-list{flex:1;min-height:0;overflow:auto;background:var(--sr-surface);border:1px solid var(--sr-line);border-radius:8px}.sr-paper-row{display:grid;grid-template-columns:24px minmax(0,1fr) auto;align-items:center;gap:10px;min-height:58px;padding:10px 12px;border-bottom:1px solid var(--sr-line)}.sr-paper-row:last-child{border-bottom:0}.sr-paper-row:hover{background:#f8fbfc}.sr-paper-select{align-self:start;padding-top:3px}.sr-paper-content{min-width:0}.sr-paper-title{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden;padding:0;border:0;background:none;color:var(--sr-text);font:600 14px/1.38 Georgia,"Noto Serif SC",serif;text-align:left;cursor:pointer}.sr-paper-title:hover{color:var(--sr-accent)}.sr-paper-meta{display:flex;align-items:center;gap:6px;min-width:0;margin-top:5px;color:var(--sr-muted);font-size:12px;white-space:nowrap;overflow:hidden}.sr-paper-meta>span:not(.sr-tag):not(.sr-folder-chip):not(.sr-row-failure):not(.sr-row-running):not(.sr-tag-more)+span:not(.sr-tag):before{content:"·";margin-right:6px}.sr-tag,.sr-folder-chip,.sr-tag-more{flex:none;padding:1px 6px;border-radius:999px;background:#eef3f3;color:#56676a;font-size:11px}.sr-folder-chip{background:#fff2b8;color:#665512}.sr-row-failure,.sr-row-running{flex:none;padding-left:7px;border-left:3px solid #ef6a55;color:#9b3f35}.sr-row-running{border-color:var(--sr-highlight-blue);color:var(--sr-accent)}.sr-row-actions{display:flex;justify-content:flex-end;gap:6px}.sr-muted{color:var(--sr-muted)}.sr-entry{display:inline-block;margin:0;padding:5px 8px;border:1px solid var(--sr-line);border-radius:5px;background:var(--sr-surface);color:var(--sr-accent);font:12px/1.2 Inter,"Noto Sans SC",sans-serif;text-decoration:none;white-space:nowrap;cursor:pointer}.sr-entry:hover:not(:disabled){border-color:var(--sr-highlight-blue);background:#f1f9ff}.sr-entry:disabled{cursor:not-allowed;color:#a0a8a7;background:#f4f4f1}.sr-empty,.sr-error{text-align:center;padding:48px!important;color:var(--sr-muted)}.sr-error{color:#9b3f35}.sr-retry{margin-left:10px}.sr-pagination{display:flex;justify-content:flex-end;align-items:center;gap:10px;padding-top:12px}.sr-batch-bar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:10px 0;border-bottom:1px solid var(--sr-line)}.sr-batch-bar[hidden]{display:none}.sr-batch-notice{min-height:20px;padding:5px 0;color:var(--sr-accent);font-size:12px}.sr-drawer-backdrop{position:absolute;z-index:4;inset:0;background:rgba(20,38,45,.3)}.sr-drawer-backdrop[hidden]{display:none}.sr-drawer{position:absolute;inset:0 0 0 auto;width:min(620px,94%);box-sizing:border-box;padding:24px;background:var(--sr-surface);border-left:1px solid var(--sr-line);box-shadow:-14px 0 30px rgba(20,38,45,.14);overflow:auto}.sr-drawer-head{display:flex;justify-content:flex-end}.sr-abstract-pair{padding:10px 0;border-bottom:1px solid var(--sr-line)}.sr-abstract-en{font-family:Georgia,serif}.sr-abstract-zh{color:var(--sr-accent)}.sr-error-note{color:#9b3f35}.sr-drawer-actions{display:flex;gap:6px;margin-top:18px}@media(max-width:900px){.sr-root{grid-template-columns:var(--sr-sidebar-width-collapsed) minmax(0,1fr)}.sr-brand,.sr-nav-label,.sr-folder-list,.sr-folder-title{display:none}.sr-main{padding:14px 12px}.sr-paper-row{grid-template-columns:22px minmax(0,1fr)}.sr-row-actions{grid-column:2;justify-content:flex-start}.sr-paper-meta{max-width:100%}}';
      style.textContent += '.sr-root{height:calc(100vh - 76px);min-height:0;max-height:100%}.sr-btn:disabled{cursor:not-allowed;opacity:.55}.sr-ingest-backdrop{position:absolute;z-index:6;inset:0;display:grid;place-items:center;padding:20px;background:rgba(32,51,47,.24)}.sr-ingest-backdrop[hidden]{display:none}.sr-ingest-dialog{width:min(520px,100%);box-sizing:border-box;padding:24px;background:var(--sr-surface);border:1px solid var(--sr-line);border-radius:6px;box-shadow:0 18px 50px rgba(32,51,47,.2)}.sr-ingest-dialog textarea{box-sizing:border-box;width:100%;resize:vertical;border:1px solid var(--sr-line);border-radius:4px;padding:10px;font:inherit}.sr-ingest-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:14px}.sr-ingest-status{min-height:1.5em;color:var(--sr-accent)}';
      style.textContent += '.sr-main{min-height:0;overflow:hidden}';
      style.textContent += '.sr-main{padding-bottom:126px}';
      style.textContent += '.sr-search-scope{display:block;margin-top:3px;color:var(--sr-muted);font-size:10px}.sr-search-matches{display:grid;gap:5px;margin-top:8px}.sr-search-match{padding:7px 9px;border-left:3px solid var(--sr-highlight-blue);border-radius:0 5px 5px 0;background:#f5f8f8}.sr-search-match-head{display:flex;align-items:center;gap:5px;flex-wrap:wrap}.sr-search-kind,.sr-search-basis,.sr-search-evidence-status,.sr-search-validity{padding:1px 5px;border-radius:999px;background:#e8eeee;color:#506165;font-size:10px}.sr-search-kind{background:#e5f2fb;color:var(--sr-accent)}.sr-search-validity{background:#f4f1e8}.sr-search-snippet{margin:4px 0 0;color:var(--sr-text);font-size:12px;white-space:normal;overflow-wrap:anywhere}.sr-search-evidence{display:inline-block;margin-top:4px;color:var(--sr-accent);font-size:11px}';
      style.textContent += UI_STYLES;
      root.appendChild(style);

      var sidebar = el('aside', 'sr-sidebar');
      var sideHead = el('div', 'sr-sidebar-head');
      sideHead.appendChild(el('span', 'sr-brand', '文献'));
      var toggle = btn('☰', function () {
        var expanded = toggle.getAttribute('aria-expanded') === 'true';
        toggle.setAttribute('aria-expanded', String(!expanded));
        root.classList.toggle('sr-collapsed', expanded);
      }, 'sr-toggle');
      toggle.setAttribute('aria-label', '收起或展开文献导航'); toggle.setAttribute('aria-expanded', 'true');
      sideHead.appendChild(toggle); sidebar.appendChild(sideHead);
      addNavigationItem(sidebar, '▦', '全部文献', '');
      addNavigationItem(sidebar, '◇', '待归类', '__unclassified__');
      sidebar.appendChild(el('div', 'sr-folder-title', '文件夹'));
      var folderList = el('div', 'sr-folder-list'); sidebar.appendChild(folderList); root.appendChild(sidebar);

      var main = el('main', 'sr-main');
      var toolbar = el('div', 'sr-toolbar');
      controls.toolbar = toolbar;
      var search = el('label', 'sr-search');
      var searchInput = document.createElement('input'); searchInput.placeholder = '搜索题名、作者、DOI、摘要或已确认结论';
      searchInput.addEventListener('input', function () { clearTimeout(searchTimer); searchTimer = setTimeout(function () { queryStore.set({ q: searchInput.value.trim() }, true); }, 250); });
      search.appendChild(searchInput); toolbar.appendChild(search);
      var addPaperButton = btn('添加文献', function () { openIngestDialog('single', addPaperButton); }, 'sr-btn sr-btn-primary'); toolbar.appendChild(addPaperButton);
      var batchPasteButton = btn('批量粘贴', function () { openIngestDialog('batch', batchPasteButton); }, 'sr-btn sr-btn-mark'); toolbar.appendChild(batchPasteButton);
      toolbar.appendChild(btn('Excel 设置',openViewsEditor,'sr-btn'));
      toolbar.appendChild(btn('文献雷达',openRadar,'sr-btn'));
      toolbar.appendChild(btn('历史对话',openLegacyHistory,'sr-btn'));
      toolbar.appendChild(filterSelect('状态', [['全部', ''], ['精读完成', 'full_read_ready'], ['失败', 'failed']], 'status'));
      var tagWrap = el('label', 'sr-filter'); tagWrap.appendChild(el('span', '', '标签'));
      var tagInput = document.createElement('input'); tagInput.placeholder = '输入标签筛选';
      tagInput.addEventListener('input', function () { clearTimeout(tagTimer); tagTimer = setTimeout(function () { queryStore.set({ tags: tagInput.value.trim() }, true); }, 250); });
      tagWrap.appendChild(tagInput); toolbar.appendChild(tagWrap);
      toolbar.appendChild(filterSelect('最近入库', [['不限', ''], ['7 天', '7'], ['30 天', '30']], 'recent_days'));
      main.appendChild(toolbar);
      controls.batchBar = el('div', 'sr-batch-bar'); controls.batchBar.hidden = true;
      controls.batchCount = el('strong', '', '已选 0 篇'); controls.batchBar.appendChild(controls.batchCount);
      function submitBatch(action, payload) { return batchActions.submit(action, payload).catch(function (error) { if (error.name !== 'AbortError') controls.batchNotice.textContent = '批量操作失败：' + userMessage(error); }); }
      controls.batchBar.appendChild(btn('下载缺失 PDF', function () { requestDownloads(selections.values()); }, 'sr-btn sr-btn-primary'));
      controls.batchBar.appendChild(btn('建立研究方向',openRadar,'sr-btn'));
      var summaryQuestion = document.createElement('input');
      summaryQuestion.setAttribute('aria-label', '对比问题');
      summaryQuestion.placeholder = '总结问题：共同发现、方法差异或结论冲突';
      summaryQuestion.maxLength = 8000;
      controls.batchBar.appendChild(summaryQuestion);
      controls.batchBar.appendChild(btn('准备对比总结', async function () {
        var ids = selections.values();
        if (!ids.length || ids.length > 20) { controls.batchNotice.textContent = '每次请选择 1–20 篇文献。'; return; }
        var question = summaryQuestion.value.trim() || '比较共同发现、方法差异、结论冲突和仍待解决的问题';
        var options = function (body) { return { method: 'POST', headers: { 'Content-Type': 'application/json', 'x-sr-csrf': '1' }, body: JSON.stringify(body) }; };
        controls.batchNotice.textContent = '正在准备…';
        try {
          for (var id of ids) await api('/sr/api/chats/open', options({ paper_id: id }));
          await api('/sr/api/chats/select', options({ selection: ids.map(function (id) { return { paper_id: id }; }), question: question.trim() }));
          controls.batchNotice.textContent = '已选择 ' + ids.length + ' 篇。请在主对话发送“总结所选文献讨论”。';
        } catch (error) { controls.batchNotice.textContent = '保存失败：' + userMessage(error); }
      }, 'sr-btn'));
      var moveFolder = el('select'); moveFolder.setAttribute('aria-label', '目标文件夹');
      controls.batchBar.appendChild(moveFolder);
      controls.batchBar.appendChild(btn('移动到文件夹', function () { submitBatch('move_folder', { folder_id: moveFolder.value || null }); }, 'sr-btn'));
      controls.batchBar.appendChild(btn('添加标签', function () { var value = window.prompt('输入标签，多个标签用逗号分隔', ''); if (value) submitBatch('add_tags', { tags: value.split(',').map(function (tag) { return tag.trim(); }).filter(Boolean) }); }, 'sr-btn'));
      controls.batchBar.appendChild(btn('移除标签', function () { var value = window.prompt('输入要移除的标签，多个标签用逗号分隔', ''); if (value) submitBatch('remove_tags', { tags: value.split(',').map(function (tag) { return tag.trim(); }).filter(Boolean) }); }, 'sr-btn'));
      controls.batchBar.appendChild(btn('取消选择', function () { selections.clear(); renderBatchToolbar(); renderNavigationList(); }, 'sr-btn'));
      main.appendChild(controls.batchBar);
      controls.batchNotice = el('div', 'sr-batch-notice'); controls.batchNotice.setAttribute('role', 'status'); controls.batchNotice.setAttribute('aria-live', 'polite'); main.appendChild(controls.batchNotice);
      function renderBatchToolbar() {
        var count = selections.size(); controls.batchBar.hidden = count === 0; controls.toolbar.hidden = count > 0; controls.batchCount.textContent = '已选 ' + count + ' 篇';
        var selectedFolder = moveFolder.value;
        moveFolder.replaceChildren(new Option('待归类', ''));
        state.folders.forEach(function (folder) { moveFolder.appendChild(new Option(folder.name, folder.folder_id)); });
        moveFolder.value = state.folders.some(function (folder) { return folder.folder_id === selectedFolder; }) ? selectedFolder : '';
      }
      controls.paperList = el('section', 'sr-paper-list'); controls.paperList.setAttribute('aria-label', '文献列表'); main.appendChild(controls.paperList);
      var pager = el('div', 'sr-pagination');
      controls.prev = btn('上一页', function () { var q = queryStore.get(); queryStore.set({ page: Math.max(1, q.page - 1) }); });
      controls.pageLabel = el('span', 'sr-muted', '第 1 页');
      controls.next = btn('下一页', function () { var q = queryStore.get(); queryStore.set({ page: q.page + 1 }); });
      pager.appendChild(controls.prev); pager.appendChild(controls.pageLabel); pager.appendChild(controls.next); main.appendChild(pager); root.appendChild(main);
      controls.backdrop = el('div', 'sr-drawer-backdrop'); controls.backdrop.hidden = true; controls.backdrop.addEventListener('click', function (event) { if (event.target === controls.backdrop) closeDrawer(); });
      controls.drawer = el('aside', 'sr-drawer'); controls.drawer.setAttribute('role', 'dialog'); controls.drawer.setAttribute('aria-modal', 'true'); controls.drawer.setAttribute('aria-hidden', 'true'); controls.drawer.setAttribute('aria-label', '文献详情');
      var drawerHead = el('div', 'sr-drawer-head'); controls.drawerClose = btn('关闭', closeDrawer, 'sr-btn'); drawerHead.appendChild(controls.drawerClose); controls.drawer.appendChild(drawerHead); controls.drawerBody = el('div'); controls.drawer.appendChild(controls.drawerBody); controls.backdrop.appendChild(controls.drawer); root.appendChild(controls.backdrop);
      controls.ingestBackdrop = el('div', 'sr-ingest-backdrop'); controls.ingestBackdrop.hidden = true;
      controls.ingestBackdrop.addEventListener('click', function (event) { if (event.target === controls.ingestBackdrop) closeIngestDialog(); });
      controls.ingestDialog = el('form', 'sr-ingest-dialog'); controls.ingestDialog.setAttribute('role', 'dialog'); controls.ingestDialog.setAttribute('aria-modal', 'true'); controls.ingestDialog.setAttribute('aria-hidden', 'true');
      controls.ingestDialog.addEventListener('submit', submitIngest);
      controls.ingestTitle = el('h2', '', '添加文献'); controls.ingestDialog.appendChild(controls.ingestTitle);
      controls.ingestHint = el('p', 'sr-muted', '输入一篇文献的题名。'); controls.ingestDialog.appendChild(controls.ingestHint);
      controls.ingestInput = document.createElement('textarea'); controls.ingestInput.setAttribute('aria-label', '文献题名'); controls.ingestInput.addEventListener('input', updateIngestSubmit); controls.ingestDialog.appendChild(controls.ingestInput);
      controls.ingestStatus = el('p', 'sr-ingest-status'); controls.ingestStatus.setAttribute('role', 'status'); controls.ingestStatus.setAttribute('aria-live', 'polite'); controls.ingestDialog.appendChild(controls.ingestStatus);
      var ingestActions = el('div', 'sr-ingest-actions'); controls.ingestCancel = btn('取消', closeIngestDialog, 'sr-btn'); controls.ingestCancel.type = 'button'; controls.ingestSubmit = btn('提交', function () {}, 'sr-btn sr-btn-primary'); controls.ingestSubmit.type = 'submit'; controls.ingestSubmit.disabled = true; ingestActions.appendChild(controls.ingestCancel); ingestActions.appendChild(controls.ingestSubmit); controls.ingestDialog.appendChild(ingestActions);
      controls.ingestBackdrop.appendChild(controls.ingestDialog); root.appendChild(controls.ingestBackdrop);
      function onKeydown(event) {
        if(root.querySelector('dialog[open]'))return;
        if (!controls.ingestBackdrop.hidden) {
          if (!ingestSubmitting && event.key === 'Escape') { closeIngestDialog(); return; }
          if (event.key === 'Tab') { var ingestFocusables = Array.from(controls.ingestDialog.querySelectorAll('button:not(:disabled),textarea:not(:disabled)')); var ingestNext = nextDialogFocus(ingestFocusables, document.activeElement, event.shiftKey); if (ingestNext) { event.preventDefault(); ingestNext.focus(); } }
          return;
        }
        if (controls.backdrop.hidden) return;
        if (event.key === 'Escape') { closeDrawer(); return; }
        if (event.key === 'Tab') { var focusables = Array.from(controls.drawer.querySelectorAll('button:not(:disabled),a[href],input:not(:disabled),summary')).filter(function (node) { return node.offsetParent !== null; }); var next = nextDialogFocus(focusables, document.activeElement, event.shiftKey); if (next) { event.preventDefault(); next.focus(); } }
      }
      document.addEventListener('keydown', onKeydown);

      var radarNotice=el('div','sr-muted');radarNotice.setAttribute('role','status');main.prepend(radarNotice);
      var radarChecking=false;
      async function checkRadar(){if(disposed||radarChecking||document.visibilityState==='hidden')return;radarChecking=true;try{var result=await api('/sr/api/radar',{method:'POST',headers:{'Content-Type':'application/json','x-sr-csrf':'1'},body:JSON.stringify({action:'notifications',acknowledge:true})});if(!disposed&&result.new_relevant_candidates.length){radarNotice.textContent='发现 '+result.new_relevant_candidates.length+' 篇相关文献。';radarNotice.appendChild(btn('查看候选',openRadar,'sr-btn'));}}catch(error){}finally{radarChecking=false;}}
      var radarTimer=setInterval(checkRadar,60000);checkRadar();

      api('/sr/api/folders').then(function (folders) {
        if (disposed || !Array.isArray(folders)) return;
        state.folders = folders;
        folders.forEach(function (folder) { addNavigationItem(folderList, '□', folder.name, folder.folder_id); });
        renderBatchToolbar();
      }).catch(function () {});
      updateNavigationSelection();
      loadLibrary();
      api('/sr/api/settings/status').then(function (snapshot) {
        if (disposed || !snapshot.onboarding || !snapshot.onboarding.show_settings) return;
        var onboarding = el('p','sr-muted','模型连接与 PDF 解析可在文献设置中配置。');
        onboarding.appendChild(btn('文献设置',openSettings,'sr-btn'));main.prepend(onboarding);
        return api('/sr/api/settings/mark-presented', { method: 'POST', headers: { 'Content-Type': 'application/json', 'x-sr-csrf': '1' }, body: JSON.stringify({ version: 'v1' }) });
      }).catch(function () {});
      return {
        root: root,
        dispose: function () {
          lifecycle.dispose();
          batchActions.dispose();
          clearTimeout(searchTimer);
          clearTimeout(tagTimer);
          clearInterval(radarTimer);
          if (request) request.abort();
          if (ingestRequest) ingestRequest.abort();
          paperSessions.dispose();
          if (viewsDialog) { var closingView=viewsDialog; closingView.close(); closingView.remove(); viewsDialog = null; }
          root.querySelectorAll('.sr-reader-editor').forEach(function(dialog){dialog.close();dialog.remove();});
          root.querySelectorAll('.sr-radar-dialog').forEach(function(dialog){dialog.close();dialog.remove();});
          root.querySelectorAll('.sr-legacy-dialog').forEach(function(dialog){dialog.close();dialog.remove();});
          document.removeEventListener('keydown', onKeydown);
          window.removeEventListener('sr-theme-change',themeChanged);
          disposed = true;
          requestSequence += 1;
        },
      };
    }

    function renderSettingsStatus(openModels) {
      var disposed = false;
      var active = null;
      var snapshot = null;
      var identity = null;
      var oauthState = null;
      var versions = {};
      var detailsOpen = false;
      var root = el('div', 'sr-settings-page');
      var style = document.createElement('style');
      style.textContent = [
        '.sr-settings-page{--sr-text:var(--dsw-alias-label-primary,#20252b);--sr-muted:var(--dsw-alias-label-secondary,#717781);--sr-line:var(--dsw-alias-border-primary,#e5e7eb);--sr-bg:var(--dsw-alias-bg-layer-1,#fff);box-sizing:border-box;container-type:inline-size;min-height:calc(100vh - 76px);padding:30px clamp(20px,4vw,54px) calc(var(--dsh-composer-height,126px) + 24px);background:var(--sr-bg);color:var(--sr-text);font-family:inherit;font-size:14px;line-height:1.55}',
        '.sr-settings-shell{max-width:900px;margin:0 auto}.sr-settings-head{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:8px}.sr-settings-head h1{margin:0 0 6px;font-size:24px;font-weight:650;letter-spacing:-.5px}.sr-settings-head p{margin:0;color:var(--sr-muted);font-size:13px}',
        '.sr-settings-group{margin-top:28px}.sr-settings-group h2{margin:0;padding-bottom:10px;border-bottom:1px solid var(--sr-line);font-size:13px;font-weight:600;color:var(--sr-muted)}.sr-setting-row{display:grid;grid-template-columns:minmax(180px,1fr) minmax(200px,1.25fr);align-items:center;gap:24px;padding:17px 0;border-bottom:1px solid var(--sr-line)}.sr-setting-row:last-child{border-bottom:0}.sr-setting-label{font-weight:550}.sr-setting-description{margin:4px 0 0;font-size:12px;color:var(--sr-muted);max-width:370px}.sr-setting-control{display:flex;justify-content:flex-end;align-items:center;gap:10px;flex-wrap:wrap;min-width:0}.sr-setting-value{font-variant-numeric:tabular-nums}.sr-setting-path{flex:1;min-width:0;overflow-wrap:anywhere;font-size:12px;text-align:right}',
        '.sr-settings-state{font-size:12px;color:var(--sr-muted)}.sr-settings-state[data-state="configured"],.sr-settings-state[data-state="authenticated"],.sr-settings-state[data-state="ready"]{color:#248467}.sr-key-form{width:100%;display:flex;gap:8px;flex-wrap:wrap}.sr-key-form input{flex:1;min-width:130px;width:0;height:36px;box-sizing:border-box;border:1px solid var(--sr-line);border-radius:7px;padding:0 10px;background:var(--sr-bg);color:var(--sr-text);font:inherit}.sr-key-meta{width:100%;display:flex;align-items:center;justify-content:space-between}',
        '.sr-settings-page button,.sr-settings-link{display:inline-flex;align-items:center;justify-content:center;box-sizing:border-box;min-height:34px;border:1px solid var(--sr-line);border-radius:7px;padding:5px 12px;background:var(--sr-bg);color:var(--sr-text);font:inherit;font-size:12px;cursor:pointer;text-decoration:none}.sr-settings-page button:hover,.sr-settings-link:hover{background:var(--dsw-alias-interactive-bg-hover,#f4f5f7)}.sr-settings-page button:disabled{cursor:wait;opacity:.5}.sr-settings-primary{background:var(--sr-accent,#3564df)!important;color:var(--sr-accent-text,#fff)!important;border-color:var(--sr-accent,#3564df)!important}.sr-settings-page .sr-settings-secondary{border:0;color:var(--sr-muted);padding:0;min-height:24px}.sr-settings-page :focus-visible{outline:2px solid #3564df;outline-offset:3px}',
        '.sr-settings-note{font-size:12px;color:var(--sr-muted)}.sr-settings-note:empty{display:none}.sr-settings-note:not(:empty){margin-top:12px}.sr-settings-details summary{cursor:pointer;color:var(--sr-muted);font-size:12px;padding:12px 0}.sr-settings-details .sr-setting-row{padding:11px 0}.sr-settings-footnote{margin-top:26px;font-size:11px;color:var(--sr-muted)}',
        '@container(max-width:590px){.sr-setting-row{grid-template-columns:1fr;gap:10px}.sr-setting-control{justify-content:flex-start}.sr-setting-path{text-align:left}.sr-settings-head{align-items:start}.sr-settings-head h1{font-size:21px}}',
      ].join('');
      style.textContent += UI_STYLES;
      root.appendChild(style);
      var shell = el('div', 'sr-settings-shell'); root.appendChild(shell);
      var head = el('header', 'sr-settings-head'); var heading = el('div'); heading.appendChild(el('h1', '', '设置与状态')); head.appendChild(heading);
      var headActions = el('div', 'sr-settings-head-actions');
      head.appendChild(headActions); shell.appendChild(head);
      var notice = el('div', 'sr-settings-note'); notice.setAttribute('role', 'status'); notice.setAttribute('aria-live', 'polite'); shell.appendChild(notice);
      var groups = el('div', 'sr-settings-groups'); shell.appendChild(groups);
      var modelSteps = el('section', 'sr-settings-group'); shell.appendChild(modelSteps);
      var modelRevision = 0, policyRequest = 0;
      function loadModelPolicy() {
        var requestId = ++policyRequest;
        modelSteps.textContent = ''; modelSteps.appendChild(el('h2', '', '模型分工'));
        modelSteps.appendChild(el('p', '', '为每个步骤选择模型和思考深度。'));
        var modelNotice = el('p', 'sr-settings-note', '正在读取已连接的模型…'); modelNotice.setAttribute('role', 'status'); modelSteps.appendChild(modelNotice);
        return api('/sr/api/settings/models').then(function (policy) {
          if (disposed || requestId !== policyRequest) return;
          modelRevision = policy.revision; modelNotice.textContent = policy.models.length ? '' : '请先连接模型服务。';
          Object.keys(policy.steps).forEach(function (step) {
            var saved = policy.steps[step], controls = el('div', 'sr-model-step-controls');
            var picker = document.createElement('select'); picker.setAttribute('aria-label', saved.label + '模型');
            var models = policy.models.slice(), matching = models.filter(function (model) { return model.id === saved.model && (!saved.provider || model.provider === saved.provider); });
            var current = matching.length === 1 ? matching[0] : null;
            var placeholder = el('option', '', models.length ? '选择模型' : '请先连接模型'); placeholder.value = ''; placeholder.disabled = true; picker.appendChild(placeholder);
            models.forEach(function (model, index) { var option = el('option', '', modelOptionLabel(model, models)); option.value = String(index); picker.appendChild(option); });
            picker.value = current ? String(models.indexOf(current)) : ''; picker.disabled = !models.length;
            var depth = document.createElement('select'); depth.setAttribute('aria-label', saved.label + '思考深度');
            function depths(preferred) {
              var selected = picker.value === '' ? null : models[Number(picker.value)]; depth.textContent = ''; depth.disabled = !selected;
              var automatic = el('option', '', '模型默认'); automatic.value = ''; depth.appendChild(automatic);
              if (!selected) return;
              selected.efforts.forEach(function (effort) { var option = el('option', '', effort); option.value = effort; depth.appendChild(option); });
              if (preferred && !selected.efforts.includes(preferred)) { var unavailable = el('option', '', preferred + '（此模型未提供）'); unavailable.value = preferred; unavailable.disabled = true; depth.appendChild(unavailable); }
              depth.value = preferred;
            }
            depths(saved.reasoningEffort);
            picker.addEventListener('change', function () { depths(models[Number(picker.value)].efforts.includes('medium') ? 'medium' : ''); save.disabled = false; });
            var feedback = el('span', 'sr-settings-note'); feedback.setAttribute('role', 'status');
            var save = btn('保存', async function () {
              if (picker.value === '') return;
              save.disabled = true; feedback.textContent = '正在保存…';
              try {
                var selected = models[Number(picker.value)], update = {}; update[step] = {provider:selected.provider,model:selected.id,reasoningEffort:depth.value};
                var result = await write('/sr/api/settings/models', 'POST', {revision:modelRevision,steps:update});
                if (disposed) return; modelRevision = result.revision; feedback.textContent = '已保存';
              } catch (error) { feedback.textContent = '未保存：' + (error.message === 'model_policy_changed' ? '设置已在其他页面更新，请刷新模型列表后重试' : userMessage(error)); }
              finally { save.disabled = false; }
            });
            save.disabled = !current;
            controls.append(picker, depth, save, feedback); row(modelSteps, saved.label, '', controls);
          });
          modelSteps.appendChild(btn('刷新模型列表', loadModelPolicy));
        }).catch(function (error) { if (!disposed) modelNotice.textContent = '模型列表读取失败：' + userMessage(error); });
      }
      loadModelPolicy();
      var appearance=el('section','sr-settings-group');appearance.appendChild(el('h2','','外观'));shell.insertBefore(appearance,groups);
      var themeChoices=el('div','sr-theme-choices'), themeNotice=el('p','sr-settings-note'), selectedTheme='paper';
      themeChoices.setAttribute('role','radiogroup');themeChoices.setAttribute('aria-label','外观主题');themeNotice.setAttribute('role','status');
      appearance.append(themeChoices,themeNotice);
      function themeValue(value){
        if(disposed)return;selectedTheme=value.id;applyTheme(root,value);
        if(!themeChoices.children.length){
          var name='sr-theme-'+crypto.randomUUID();
          value.presets.forEach(function(theme){
            var card=el('label','sr-theme-card'),input=el('input'),preview=el('span','sr-theme-preview');
            input.type='radio';input.name=name;input.value=theme.id;input.setAttribute('aria-label',theme.label);
            applyTheme(preview,theme);preview.setAttribute('aria-hidden','true');
            preview.append(el('span','sr-theme-preview-rail'),el('span','sr-theme-preview-page'));
            card.append(input,preview,el('span','sr-theme-name',theme.label));themeChoices.appendChild(card);
            input.addEventListener('change',function(){saveTheme(theme.id);});
          });
        }
        themeChoices.querySelectorAll('input').forEach(function(input){input.checked=input.value===selectedTheme;});
      }
      async function saveTheme(id){
        themeChoices.querySelectorAll('input').forEach(function(input){input.disabled=true;});themeNotice.textContent='正在应用…';
        try{var value=await write('/sr/api/views','POST',{action:'theme_save',preset:id});themeValue(value);window.dispatchEvent(new CustomEvent('sr-theme-change',{detail:value}));themeNotice.textContent='已应用';}
        catch(error){themeChoices.querySelectorAll('input').forEach(function(input){input.checked=input.value===selectedTheme;});themeNotice.textContent='未应用：'+userMessage(error);}
        finally{themeChoices.querySelectorAll('input').forEach(function(input){input.disabled=false;});}
      }
      function themeChanged(event){themeValue(event.detail);}
      window.addEventListener('sr-theme-change',themeChanged);
      write('/sr/api/views','POST',{action:'theme_get'}).then(themeValue).catch(function(){themeNotice.textContent='主题暂不可用，请重新打开设置。';});

      function statusText(value) {
        var labels = { authenticated: '已登录', unauthenticated: '未登录', unsupported_auth: '需要登录 Codex 订阅', ready: '可用', configured: '已配置', logged_in: '已登录', valid: '已连接', none: '未登录', expired: '需要重新认证', unreachable: '暂时无法检测', installed: '已安装', not_installed: '未安装', empty: '尚无文献', not_checked: '尚未检测', not_configured: '未配置', unavailable: '暂不可用', failed: '检测失败' };
        return labels[value] || '暂不可用';
      }
      function stateLabel(status) {
        var label = el('span', 'sr-settings-state', statusText(status)); label.dataset.state = status || ''; return label;
      }
      function group(title) {
        var section = el('section', 'sr-settings-group'); section.appendChild(el('h2', '', title)); groups.appendChild(section); return section;
      }
      function row(section, title, description, control) {
        var line = el('div', 'sr-setting-row'); var label = el('div'); label.appendChild(el('div', 'sr-setting-label', title));
        if (description) label.appendChild(el('p', 'sr-setting-description', description));
        var value = el('div', 'sr-setting-control');
        if (typeof control === 'string') value.appendChild(el('span', 'sr-setting-value', control));
        else if (control) value.appendChild(control);
        line.appendChild(label); line.appendChild(value); section.appendChild(line); return value;
      }
      function renderSnapshot(value) {
        if (disposed) return;
        snapshot = value; versions = value.versions || versions;
        // Metadata refresh must not discard a key the user is still typing.
        var previousInput = groups.querySelector('.sr-key-form input');
        var draftKey = previousInput ? previousInput.value : '';
        var focusedKey = previousInput && document.activeElement === previousInput;
        var previousDetails = groups.querySelector('details'); if (previousDetails) detailsOpen = previousDetails.open;
        groups.textContent = '';
        var download = snapshot.download || {}; var mineru = snapshot.mineru || {}; var local = mineru.local || {}; var apiStatus = mineru.api || {}; var library = snapshot.library || {};
        var models = group('模型与连接');
        var modelButton = btn('管理模型连接', function () { if (openModels) Promise.resolve().then(openModels).catch(showError); });
        modelButton.disabled = !openModels;
        row(models, '模型服务', '', modelButton);
        if (identity) {
          var oauth = row(models, 'Codex 订阅', '需为此工作台单独登录。', stateLabel(oauthState ? oauthState.status : 'not_checked'));
          var loginLink = el('a', 'sr-settings-link', oauthState && oauthState.authenticated ? '管理登录' : '连接 Codex');
          loginLink.href = '/api/codex-oauth/ui'; loginLink.target = '_blank'; loginLink.rel = 'noopener'; oauth.appendChild(loginLink);
        }
        var parsing = group('PDF 解析');
        var keyForm = el('div', 'sr-key-form'); var keyInput = document.createElement('input'); keyInput.type = 'password'; keyInput.placeholder = '粘贴 MinerU API Key'; keyInput.autocomplete = 'off'; keyForm.appendChild(keyInput);
        keyInput.setAttribute('aria-label', 'MinerU API Key'); keyInput.value = draftKey;
        function keyAction(button, token) {
          keyInput.value = ''; button.disabled = true;
          updateMineruKey(api, token).then(function (next) { renderSnapshot(next); notice.textContent = token === null ? 'MinerU API Key 已删除。' : '密钥已保存，连接待验证。'; }).catch(showError).finally(function () { button.disabled = false; });
        }
        var saveKey = btn(apiStatus.status === 'configured' ? '替换密钥' : '保存密钥', function () {
          var token = keyInput.value.trim(); if (!token) { keyInput.focus(); return; } keyAction(saveKey, token);
        }, 'sr-settings-primary'); keyForm.appendChild(saveKey);
        var keyMeta = el('div', 'sr-key-meta'); keyMeta.appendChild(stateLabel(apiStatus.status)); keyForm.appendChild(keyMeta);
        if (apiStatus.status === 'configured') {
          var deleteKey = btn('删除密钥', function () { keyAction(deleteKey, null); }, 'sr-settings-secondary'); keyMeta.appendChild(deleteKey);
        }
        row(parsing, 'MinerU API Key', '将 PDF 转为可阅读的正文。', keyForm);
        var libraryGroup = group('文献库');
        row(libraryGroup, '本地文献库', '', (Number(library.papers) || 0) + ' 篇文献');
        row(libraryGroup, 'Excel 待同步', '同步前请保存并关闭 Excel。', (Number(library.xlsx_pending) || 0) + ' 篇');
        var location = row(libraryGroup, '存储位置', '');
        location.appendChild(el('span', 'sr-setting-path', library.data_root || '位置暂不可用'));
        if (library.data_root) location.appendChild(btn('复制路径', function () {
          Promise.resolve().then(function () { return navigator.clipboard.writeText(library.data_root); }).then(function () { notice.textContent = '文献库路径已复制。'; }).catch(showError);
        }));
        var about = group('关于');
        row(about, identity ? 'Deep Literature for Codex' : 'Deep Literature for DSH', '', identity ? identity.version : (versions.plugin || '版本暂不可用'));
        var details = el('details', 'sr-settings-details'); details.open = detailsOpen; details.appendChild(el('summary', '', '版本与服务状态')); about.appendChild(details);
        row(details, '文献引擎', '', snapshot.engine_version || '版本暂不可用');
        row(details, '文献插件', '', versions.plugin || '版本暂不可用');
        row(details, 'DSH', '', (identity && identity.dshVersion) || versions.dsh || '版本暂不可用');
        row(details, 'PDF 自动获取', '获取开放全文，也可添加本地 PDF。', stateLabel(download.status));
        row(details, '本机 MinerU', '未安装时可使用上方配置的 MinerU API。', stateLabel(local.status));
        var recheck = btn('重新检测', function () {
          recheck.disabled = true;
          Promise.all([write('/sr/api/settings/recheck', 'POST', { targets: ['download', 'mineru_local', 'mineru_api'] }), refreshConnection()])
            .then(function (results) { renderSnapshot(results[0]); notice.textContent = '状态已更新。'; }).catch(showError).finally(function () { recheck.disabled = false; });
        });
        row(details, '更新状态', '', recheck);
        if (focusedKey) keyInput.focus();
      }
      function write(path, method, body) { return api(path, { method: method, headers: { 'Content-Type': 'application/json', 'x-sr-csrf': '1' }, body: method === 'DELETE' ? undefined : JSON.stringify(body || {}) }); }
      function showError(error) { if (!disposed) notice.textContent = '操作失败：' + userMessage(error); }
      async function refreshConnection() {
        try {
          var current = await api('/__workbench/identity');
          if (current.product !== 'codex-scientific-reading') return;
          identity = current;
          try { oauthState = await api('/api/codex-oauth'); } catch (error) { oauthState = { status: 'unavailable' }; }
        } catch (error) { /* 原生插件没有 Codex 工作台身份接口。 */ }
      }
      function load() { if (active) active.abort(); active = new AbortController(); return api('/sr/api/settings/status', { signal: active.signal }).then(renderSnapshot).catch(function (error) { if (error.name !== 'AbortError') showError(error); }); }
      load();
      refreshConnection().then(function () { if (snapshot) renderSnapshot(snapshot); });
      function onFocus() { loadModelPolicy(); refreshConnection().then(function () { if (snapshot) renderSnapshot(snapshot); }); }
      window.addEventListener('focus', onFocus);
      shell.appendChild(el('p', 'sr-settings-footnote', '密钥保存在本机系统凭据库；使用 MinerU API 解析时才会发送论文 PDF。'));
      return { root: root, dispose: function () { disposed = true; window.removeEventListener('focus', onFocus); window.removeEventListener('sr-theme-change',themeChanged); if (active) active.abort(); } };
    }
    // ── 设置卡片（settings.plugin.item，key=scientific-reading）─────
    var SR_NS = 'scientific-reading';
    function SettingsCard() {
      var root = el('div', 'sr-settings-card');
      root.style.cssText = 'padding:14px 4px;font-size:13px;line-height:1.6';
      root.appendChild(el('strong', '', '文献工作流设置'));
      root.appendChild(el('p', '', '请从右侧栏打开“文献设置”。'));
      return root;
    }

    exports.inject = ['slots', 'sessions', 'sidebarRight', 'sidebarRightTabs'];
    function apply(ctx) {
      ctx.effect(function () {
        var pages=[{id:'scientific-reading-library',page:'literature',label:'文献库'}, {id:'scientific-reading-settings',page:'settings',label:'文献设置'}];
        var disposers=[];
        async function openWorkbench(page) {
          try {
            if (!ctx.sessions.list.getSnapshot().current) {
              var sessionId = await ctx.sessions.create();
              ctx.sessions.open(sessionId);
              // Let the newly selected session mount its native sidebar seat.
              await new Promise(function(resolve){requestAnimationFrame(function(){requestAnimationFrame(resolve);});});
            }
            ctx.sidebarRight.openTab(page.id);
          } catch (error) { window.alert('打开失败：' + userMessage(error)); }
        }
        function EntryButtons(props) {
          return React.createElement('div',{style:{display:'flex',gap:'4px'}},pages.map(function(page,index){
            return React.createElement('button',{key:page.id,type:'button',title:page.label,'aria-label':'打开'+page.label,'data-sr-workbench-entry':page.id,disabled:props.disabled,
              style:{display:'grid',placeItems:'center',width:'32px',height:'32px',border:0,borderRadius:'6px',background:'transparent',color:'inherit',cursor:'pointer'},
              onClick:function(){return props.onOpen(page);}},
              React.createElement('svg',{width:18,height:18,viewBox:'0 0 24 24',fill:'none',stroke:'currentColor',strokeWidth:1.6,'aria-hidden':true},
                React.createElement('path',{d:index?'M4 7h16M4 17h16M8 4v6M16 14v6':'M12 5v15M3 4h5a4 4 0 0 1 4 2 4 4 0 0 1 4-2h5v15h-5a4 4 0 0 0-4 2 4 4 0 0 0-4-2H3Z'})));
          }));
        }
        function EmptySessionEntry() {
          var list = React.useSyncExternalStore(ctx.sessions.list.subscribe,ctx.sessions.list.getSnapshot);
          var busy = React.useState(false);
          if (list.current && !list.byId[list.current]?.blank) return null;
          return React.createElement('div',{className:'sr-empty-workbench-entry',style:{position:'absolute',right:'16px',top:'12px',pointerEvents:'auto'}},
            React.createElement('style',null,'body:has([data-sidebar-right-open]) .sr-empty-workbench-entry{display:none}'),
            React.createElement(EntryButtons,{disabled:busy[0] || list.phase === 'pending',onOpen:async function(page){busy[1](true);await openWorkbench(page);busy[1](false);}}));
        }
        pages.forEach(function(page,index){
          disposers.push(ctx.sidebarRightTabs.register({id:page.id,kind:page.id,title:function(){return page.label;},guide:[{order:10+index,title:function(){return page.label;}}]}));
          disposers.push(ctx.slots.inject('sidebar.right.pane.tab',function(){return ctx.slots.register({name:'sidebar.right.pane.tab',key:page.id},function(props){return React.createElement(ModeView,Object.assign({},props,{page:page.page}));});}));
        });
        disposers.push(ctx.slots.inject('conversation.session.header.utilities', function () {
          return ctx.slots.register({name:'conversation.session.header.utilities', id:'scientific-reading', order:20}, function () {
            return React.createElement(EntryButtons,{onOpen:openWorkbench});
          });
        }));
        disposers.push(ctx.slots.inject('shell.overlay',function(){return ctx.slots.register({name:'shell.overlay',id:'scientific-reading-entry',order:20},EmptySessionEntry);}));
        return function(){disposers.reverse().forEach(function(dispose){dispose();});};
      }, 'sr-workbench-entry');
      ctx.effect(function () {
        var paper = new URL(window.location.href).searchParams.get('sr-paper');
        if (paper) api('/sr/api/chats/open', {method:'POST', headers:{'Content-Type':'application/json','x-sr-csrf':'1'}, body:JSON.stringify({paper_id:paper})}).then(async function (result) {
          await ctx.sessions.refresh(); ctx.sessions.open(result.session_id);
          var url = new URL(window.location.href); url.searchParams.delete('sr-paper'); window.history.replaceState(null, '', url);
        }).catch(function (error) { window.alert('对话打开失败：' + userMessage(error)); });
      }, 'sr-paper-link');
      function openNativeModels() {
        var section = ctx.slots.entries('settings.section').find(function (entry) { return entry.options.id === 'models'; });
        var label = section && (typeof section.options.label === 'function' ? section.options.label() : section.options.label);
        var shell = document.querySelector('[data-slot="sidebar.settings"]');
        var trigger = shell && shell.querySelector('button[aria-haspopup="dialog"]');
        if (!trigger || typeof label !== 'string') return Promise.reject(new Error('请从 DSH 左下角设置打开模型配置。'));
        // DSH rc.7 keeps panel navigation inside its settings shell. Reuse the
        // public slot wrapper and localized nav label; never duplicate its form.
        return new Promise(function (resolve, reject) {
          var observer, timer;
          function select() {
            var navigation = shell.querySelector('[role="dialog"] nav');
            var target = navigation && Array.from(navigation.querySelectorAll('button')).find(function (button) { return button.textContent.trim() === label; });
            if (!target) return false;
            if (observer) observer.disconnect(); clearTimeout(timer); target.click(); resolve(); return true;
          }
          observer = new MutationObserver(select);
          observer.observe(shell, { childList: true, subtree: true });
          timer = setTimeout(function () { observer.disconnect(); reject(new Error('请在已打开的 DSH 设置中选择“模型”。')); }, 2000);
          trigger.click(); select();
        });
      }
      function ModeView(props) {
        var mountController = React.useMemo(function () {
          return createMountController(function () {
            return props.page === 'settings' ? renderSettingsStatus(openNativeModels) : renderLiterature(ctx.sessions, function(){ctx.sidebarRight.openTab('scientific-reading-settings');});
          });
        }, [props.page]);
        return React.createElement('section', {className:'sr-workbench-panel','aria-label':props.page === 'settings' ? '文献设置' : '文献库', ref: mountController.ref});
      }
      ctx.effect(function () {
        ctx.slots.inject('settings.plugin.item', function () {
          return ctx.slots.register({
            name: 'settings.plugin.item',
            key: SR_NS,
          }, function () { return { render: function () {
            return React.createElement('div', { ref: function (el) {
              if (el && !el.dataset.srCardMounted) { el.dataset.srCardMounted = '1'; el.appendChild(SettingsCard()); }
            } });
          } }; });
        });
      }, 'sr-settings-card');
    }
    exports.apply = apply;
    return module.exports;
  }
});
