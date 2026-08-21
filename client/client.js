// @dsh-external/dsh-scientific-reading — 文献页（conversation.view tab，纯 DOM 实现）
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
    function statusBadge(status) {
      var colors = { library_ready: '#5b8def', pdf_ready: '#7a9e4b', parsed_fast: '#b8860b', parsed_mineru: '#8b6914', quick_read_ready: '#2e8b57', full_read_ready: '#4169e1', waiting_agent: '#c0392b', running: '#2e8b57', completed: '#2e8b57', failed: '#c0392b' };
      var s = el('span', 'sr-badge', status);
      s.style.background = colors[status] || '#888';
      return s;
    }

    // ── 主视图 ───────────────────────────────────────────────
    var state = { papers: [], selected: null, filter: '', search: '' };

    function refreshList() {
      return api('/sr/api/papers').then(function (data) {
        state.papers = data.papers || [];
        renderTable();
      });
    }

    function selectPaper(id) {
      state.selected = id;
      api('/sr/api/paper/' + encodeURIComponent(id)).then(function (data) {
        renderDetail(data);
      }).catch(function (e) {
        renderDetail({ error: e.message });
      });
    }

    function renderTable() {
      var tbody = state.tableBody;
      tbody.textContent = '';
      var q = state.search.toLowerCase();
      var rows = state.papers.filter(function (p) {
        if (q && !(String(p.title || '').toLowerCase().includes(q) || String(p.doi || '').toLowerCase().includes(q))) return false;
        return true;
      });
      if (rows.length === 0) {
        var tr = el('tr'); tr.appendChild(el('td', '', '（空）')); tr.cells && tr.cells.length; tbody.appendChild(tr);
        return;
      }
      rows.forEach(function (p) {
        var tr = el('tr');
        tr.style.cursor = 'pointer';
        if (p.paper_id === state.selected) tr.style.background = '#eef4ff';
        var td1 = el('td'); td1.appendChild(statusBadge(p.status || 'unknown'));
        var td2 = el('td', 'sr-title', p.title || '(无题名)');
        var td3 = el('td', 'sr-dim', (p.year ? String(p.year) : ''));
        var td4 = el('td', 'sr-dim', (p.doi || '').slice(0, 40));
        tr.appendChild(td1); tr.appendChild(td2); tr.appendChild(td3); tr.appendChild(td4);
        tr.addEventListener('click', function () { selectPaper(p.paper_id); });
        tbody.appendChild(tr);
      });
    }

    function renderDetail(data) {
      var box = state.detail;
      box.textContent = '';
      if (data.error) { box.appendChild(el('p', 'sr-err', '错误：' + data.error)); return; }
      var item = data.item || {};
      var title = el('h3', 'sr-h3', item.title || '(无题名)');
      var meta = el('p', 'sr-dim', (item.authors || []).join('、') + ' · ' + (item.year || '?') + ' · ' + (item.journal || ''));
      var doi = el('p', 'sr-dim', 'DOI: ' + (item.doi || '—') + ' · ' + (data.paper_id || ''));
      box.appendChild(title); box.appendChild(meta); box.appendChild(doi);
      var job = data.job;
      if (job) {
        var st = el('p'); st.appendChild(el('span', 'sr-dim', '工作流状态：')); st.appendChild(statusBadge(job.status || '?'));
        box.appendChild(st);
      }
      // 操作区
      var actions = el('div', 'sr-actions');
      var id = data.paper_id;
      actions.appendChild(btn('解析', function () {
        api('/sr/api/paper/' + encodeURIComponent(id) + '/parse', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).then(function (r) { alert('解析已排队: ' + (r.job_id || '')); selectPaper(id); }).catch(function (e) { alert(e.message); });
      }));
      actions.appendChild(btn('浅读', function () {
        api('/sr/api/paper/' + encodeURIComponent(id) + '/quick-read', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).then(function (r) { alert('浅读已排队: ' + (r.job_id || '')); selectPaper(id); }).catch(function (e) { alert(e.message); });
      }));
      actions.appendChild(btn('精读', function () {
        api('/sr/api/paper/' + encodeURIComponent(id) + '/full-read', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).then(function (r) { alert('精读已排队: ' + (r.job_id || '')); selectPaper(id); }).catch(function (e) { alert(e.message); });
      }));
      if (item.doi) {
        actions.appendChild(btn('下载PDF', function () {
          api('/sr/api/paper/' + encodeURIComponent(id) + '/download', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ identifier: item.doi }) }).then(function (r) {
            var d = r.download || {};
            alert('下载: ' + d.status + ' ' + (d.paper ? d.paper.pdf_path : ''));
            selectPaper(id);
          }).catch(function (e) { alert(e.message); });
        }));
      }
      // 附件：本地 PDF（base64 上传）
      var fileInput = document.createElement('input');
      fileInput.type = 'file'; fileInput.accept = '.pdf';
      fileInput.style.display = 'none';
      fileInput.addEventListener('change', function () {
        var file = fileInput.files && fileInput.files[0];
        if (!file) return;
        var reader = new FileReader();
        reader.onload = function () {
          var b64 = String(reader.result).split(',')[1] || '';
          api('/sr/api/paper/' + encodeURIComponent(id) + '/attach', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pdf_b64: b64 }) }).then(function () { alert('已挂接 PDF'); selectPaper(id); }).catch(function (e) { alert(e.message); });
        };
        reader.readAsDataURL(file);
      });
      var attachBtn = btn('挂接本地PDF', function () { fileInput.click(); });
      actions.appendChild(attachBtn);
      box.appendChild(fileInput);
      // 笔记链接
      if (data.outputs && data.outputs.indexOf('reading/quick_read.md') !== -1) {
        var link = el('a', 'sr-link', '打开浅读笔记');
        link.href = '/sr/reading/' + encodeURIComponent(id);
        link.target = '_blank';
        box.appendChild(link);
      }
      if (data.outputs && data.outputs.indexOf('reading/full/output/reader_full.html') !== -1) {
        var link2 = el('a', 'sr-link', '打开精读HTML');
        link2.href = '/sr/reader/' + encodeURIComponent(id);
        link2.target = '_blank';
        box.appendChild(link2);
      }
      // 笔记预览
      if (data.reading) {
        var pre = el('pre', 'sr-note', data.reading.slice(0, 3000) + (data.reading.length > 3000 ? '\n…（截断，点上方链接看全文）' : ''));
        box.appendChild(pre);
      }
      box.appendChild(actions);
    }

    function renderLiterature() {
      var root = el('div', 'sr-root');
      root.style.cssText = 'display:flex;flex-direction:column;height:100%;font-family:system-ui;font-size:13px;color:#1a1a1a;padding:8px;box-sizing:border-box;overflow:hidden';
      // 工具栏
      var toolbar = el('div', 'sr-toolbar');
      toolbar.style.cssText = 'display:flex;gap:8px;align-items:center;padding-bottom:8px;border-bottom:1px solid #ddd;flex-wrap:wrap';
      var addInput = document.createElement('input');
      addInput.placeholder = 'DOI 或 题名，如 10.48550/arXiv.1706.03762';
      addInput.style.cssText = 'flex:1;min-width:260px;padding:5px 8px;border:1px solid #bbb;border-radius:4px';
      toolbar.appendChild(addInput);
      toolbar.appendChild(btn('添加文献', function () {
        var v = addInput.value.trim();
        if (!v) return;
        var isDoi = /^10\./.test(v);
        var payload = isDoi ? { title: v, doi: v } : { title: v };
        api('/sr/api/paper', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) }).then(function (r) {
          alert('已添加: ' + r.paper_id + (r.dedupe === 'exact' ? '（库中已存在）' : ''));
          refreshList().then(function () { selectPaper(r.paper_id); });
        }).catch(function (e) { alert(e.message); });
      }, 'sr-btn-primary'));
      toolbar.appendChild(btn('刷新', function () { refreshList(); }));
      root.appendChild(toolbar);
      // 三栏主体
      var body = el('div', 'sr-body');
      body.style.cssText = 'display:flex;gap:8px;flex:1;min-height:0;padding-top:8px';
      // 左栏：搜索/筛选
      var left = el('div', 'sr-left');
      left.style.cssText = 'width:200px;flex-shrink:0;border-right:1px solid #ddd;padding-right:8px;overflow:auto';
      left.appendChild(el('div', 'sr-dim', '筛选'));
      var searchInput = document.createElement('input');
      searchInput.placeholder = '搜索标题/DOI';
      searchInput.style.cssText = 'width:100%;padding:4px 6px;margin:4px 0 8px;border:1px solid #bbb;border-radius:4px';
      searchInput.addEventListener('input', function () { state.search = searchInput.value; renderTable(); });
      left.appendChild(searchInput);
      left.appendChild(el('div', 'sr-dim', '全部文献（' + state.papers.length + '）'));
      body.appendChild(left);
      // 中栏：论文表格
      var mid = el('div', 'sr-mid');
      mid.style.cssText = 'flex:1;min-width:0;overflow:auto';
      var table = document.createElement('table');
      table.style.cssText = 'width:100%;border-collapse:collapse';
      var thead = el('thead');
      var hr = el('tr');
      ['状态', '标题', '年份', 'DOI'].forEach(function (h) { var th = el('th', '', h); th.style.cssText = 'text-align:left;padding:4px 8px;border-bottom:2px solid #ddd;position:sticky;top:0;background:#fff'; hr.appendChild(th); });
      thead.appendChild(hr);
      table.appendChild(thead);
      state.tableBody = el('tbody');
      table.appendChild(state.tableBody);
      mid.appendChild(table);
      body.appendChild(mid);
      // 右栏：详情
      var right = el('div', 'sr-right');
      right.style.cssText = 'width:380px;flex-shrink:0;border-left:1px solid #ddd;padding-left:8px;overflow:auto';
      state.detail = right;
      right.appendChild(el('p', 'sr-dim', '选择左侧论文查看详情'));
      body.appendChild(right);
      root.appendChild(body);
      // 初始加载
      refreshList();
      return root;
    }

    // ── 设置卡片（settings.plugin.item，key=scientific-reading）─────
    var SR_NS = 'scientific-reading';
    var SR_FIELDS = [
      { key: 'dataRoot', label: '数据根目录', hint: '空 = ~/scientific-reading-data', type: 'text' },
      { key: 'python', label: 'Python 解释器', hint: 'scansci-pdf 安装/调用用', type: 'text' },
      { key: 'scansciExe', label: 'scansci-pdf 可执行', hint: 'PATH 名或绝对路径', type: 'text' },
      { key: 'school', label: '学校名（CARSI/WebVPN）', hint: '机构访问用，支持部分匹配', type: 'text' },
      { key: 'legalOnly', label: '只走合法来源', hint: '关闭则启用 Sci-Hub/LibGen 灰色来源', type: 'bool' },
      { key: 'outputDir', label: '下载输出目录', hint: '空 = <dataRoot>/downloads', type: 'text' },
      { key: 'loginType', label: '机构登录类型', hint: 'cookies | webvpn | carsi | ezproxy | custom', type: 'text' },
      { key: 'scansciPython', label: 'scansci Python 路径', hint: '空 = 自动探测 uv 工具环境', type: 'text' },
      { key: 'enginePython', label: '引擎 Python 路径', hint: '空 = 自动探测（优先复用 scansci 环境）', type: 'text' },
      { key: 'feishuConfig', label: '飞书配置 JSON 路径', hint: 'feishu-config-v1（含 app_token/table_id/field_map），须在仓库外', type: 'text' },
    ];
    var srCardRoot = null;
    var srCardInputs = {};
    var srCardScope = null;
    var srCardDrafts = {};

    function buildSettingsCard() {
      var root = el('div', 'sr-settings-card');
      root.style.cssText = 'display:flex;flex-direction:column;gap:10px;padding:14px 4px';
      var head = el('div');
      head.style.cssText = 'display:flex;align-items:center;gap:8px';
      head.appendChild(el('span', '', '文献工作流设置'));
      var badge = el('span', 'sr-settings-badge', '…');
      badge.style.cssText = 'font-size:11px;color:#fff;border-radius:999px;padding:1px 8px;background:#888';
      head.appendChild(badge);
      root.appendChild(head);
      srCardFields().forEach(function (f) {
        var row = el('div');
        row.style.cssText = 'display:flex;flex-direction:column;gap:3px';
        var lab = el('label', '', f.label);
        lab.style.cssText = 'font-size:12px;font-weight:500;color:var(--dsw-alias-label-primary,#333)';
        row.appendChild(lab);
        var input;
        if (f.type === 'bool') {
          input = document.createElement('input');
          input.type = 'checkbox';
          input.style.cssText = 'width:16px;height:16px;cursor:pointer';
          input.addEventListener('change', function () { srCardDrafts[f.key] = input.checked; });
        } else {
          input = document.createElement('input');
          input.type = 'text';
          input.style.cssText = 'border:1px solid var(--dsw-alias-border-l2,#ccc);border-radius:6px;padding:5px 9px;font-size:13px;background:var(--dsw-alias-bg-layer-3,#fff);color:var(--dsw-alias-label-primary,#333)';
          input.addEventListener('input', function () {
            var v = input.value.trim();
            srCardDrafts[f.key] = v === '' ? null : v;
          });
        }
        srCardInputs[f.key] = input;
        row.appendChild(input);
        if (f.hint) {
          var hint = el('div', 'sr-dim', f.hint);
          hint.style.cssText = 'font-size:11px;color:var(--dsw-alias-label-tertiary,#999)';
          row.appendChild(hint);
        }
        root.appendChild(row);
      });
      var actions = el('div');
      actions.style.cssText = 'display:flex;gap:8px;margin-top:6px';
      var saveBtn = btn('保存', function () {
        if (!srCardScope) return;
        var any = false;
        Object.keys(srCardDrafts).forEach(function (k) {
          var v = srCardDrafts[k];
          if (v === null) { srCardScope.unset(k); any = true; }
          else { srCardScope.set(k, v); any = true; }
        });
        if (!any) { alert('没有变更'); return; }
        srCardDrafts = {};
        saveBtn.disabled = true;
        setTimeout(function () { saveBtn.disabled = false; }, 800);
      });
      saveBtn.style.cssText = 'background:#2e8b57;color:#fff;border:none;border-radius:6px;padding:6px 16px;cursor:pointer;font-size:13px;font-weight:500';
      var resetBtn = btn('恢复默认', function () {
        if (!srCardScope) return;
        SR_FIELDS.forEach(function (f) { srCardScope.unset(f.key); });
        srCardDrafts = {};
        resetBtn.disabled = true;
        setTimeout(function () { resetBtn.disabled = false; }, 800);
      });
      resetBtn.style.cssText = 'background:transparent;color:#666;border:1px solid #ccc;border-radius:6px;padding:6px 16px;cursor:pointer;font-size:13px';
      actions.appendChild(saveBtn);
      actions.appendChild(resetBtn);
      root.appendChild(actions);
      return root;
    }
    function srCardFields() { return SR_FIELDS; }
    function applyCardSnapshot() {
      if (!srCardScope || !srCardRoot) return;
      var snap = srCardScope.getSnapshot();
      var badge = srCardRoot.querySelector('.sr-settings-badge');
      if (badge) {
        if (snap.status !== 'ready') {
          badge.textContent = snap.status;
          badge.style.background = '#888';
        } else {
          badge.textContent = snap.writable ? '可编辑' : '只读';
          badge.style.background = snap.writable ? '#2e8b57' : '#888';
        }
      }
      if (snap.status !== 'ready') return;
      var value = snap.value || {};
      SR_FIELDS.forEach(function (f) {
        var input = srCardInputs[f.key];
        if (!input) return;
        if (f.type === 'bool') input.checked = !!value[f.key];
        else {
          var v = value[f.key];
          input.value = (v === undefined || v === null) ? '' : String(v);
        }
      });
    }
    function SettingsCard() {
      if (srCardRoot) { applyCardSnapshot(); return srCardRoot; }
      srCardRoot = buildSettingsCard();
      if (srCardScope) applyCardSnapshot();
      return srCardRoot;
    }

    // ── 注册 conversation.view 标签 + settings.plugin.item 卡片 ─────
    exports.inject = ['slots', 'settingsScope', 'connection', 'remote'];
    function apply(ctx) {
      ctx.effect(function () {
        return ctx.slots.inject('conversation.view', function () {
          return ctx.slots.register({
            name: 'conversation.view',
            id: 'literature',
            order: 20,
            label: function () { return '文献'; },
          }, function () { return { render: function () {
            return React.createElement('div', { ref: function (el) {
              if (el && !el.dataset.srMounted) { el.dataset.srMounted = '1'; el.appendChild(renderLiterature()); }
            } });
          } }; });
        });
      }, 'sr-literature-tab');
      ctx.effect(function () {
        srCardScope = ctx.settingsScope.bind({ namespace: SR_NS });
        var off = srCardScope.subscribe(function () { applyCardSnapshot(); });
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
        return function () { try { off(); } catch (e) {} };
      }, 'sr-settings-card');
    }
    exports.apply = apply;
    return module.exports;
  }
});
