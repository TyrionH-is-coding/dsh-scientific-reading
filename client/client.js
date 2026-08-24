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
      s.style.cssText = 'display:inline-block;background:' + (colors[status] || '#888') + ';color:#fff;border-radius:999px;padding:2px 8px;line-height:1.35;white-space:nowrap;font-size:12px';
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
      state.countLabel.textContent = '全部文献（' + state.papers.length + '）';
      tbody.textContent = '';
      var q = state.search.toLowerCase();
      var rows = state.papers.filter(function (p) {
        if (q && !(String(p.title || '').toLowerCase().includes(q) || String(p.doi || '').toLowerCase().includes(q))) return false;
        return true;
      });
      if (rows.length === 0) {
        var tr = el('tr'); var empty = el('td', 'sr-dim', '（空）'); empty.colSpan = 4; empty.style.padding = '12px 8px'; tr.appendChild(empty); tbody.appendChild(tr);
        return;
      }
      rows.forEach(function (p) {
        var tr = el('tr');
        tr.style.cursor = 'pointer';
        if (p.paper_id === state.selected) tr.style.background = '#eef4ff';
        var td1 = el('td'); td1.appendChild(statusBadge(p.status || 'unknown'));
        var td2 = el('td', 'sr-title', p.title || '(无题名)');
        var td3 = el('td', 'sr-dim', (p.year ? String(p.year) : ''));
        var td4 = el('td', 'sr-dim', p.doi || '');
        td1.style.cssText = 'padding:7px 8px;border-bottom:1px solid #eee;vertical-align:top;white-space:nowrap';
        td2.style.cssText = 'padding:7px 8px;border-bottom:1px solid #eee;vertical-align:top;overflow:hidden;text-overflow:ellipsis;white-space:nowrap';
        td3.style.cssText = 'padding:7px 8px;border-bottom:1px solid #eee;vertical-align:top;white-space:nowrap';
        td4.style.cssText = 'padding:7px 8px;border-bottom:1px solid #eee;vertical-align:top;overflow:hidden;text-overflow:ellipsis;white-space:nowrap';
        td2.title = p.title || '(无题名)';
        td4.title = p.doi || '';
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
      actions.appendChild(btn('开始精读', function () {
        api('/sr/api/paper/' + encodeURIComponent(id) + '/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).then(function (r) { alert('精读父任务: ' + (r.parent_job_id || '')); selectPaper(id); }).catch(function (e) { alert(e.message); });
      }));
      var gateReason = job && (job.reason_code || (job.detail && job.detail.reason_code));
      var needsPdf = job && (job.status === 'needs_user' || job.status === 'waiting_user') && gateReason === 'pdf_required';
      if (needsPdf && item.doi) {
        actions.appendChild(btn('机构浏览器获取PDF', function () {
          api('/sr/api/paper/' + encodeURIComponent(id) + '/download', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ identifier: item.doi, job_id: item.active_job_id }) }).then(function (r) {
            alert('PDF 已挂接，精读继续: ' + r.parent_job_id);
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
          api('/sr/api/paper/' + encodeURIComponent(id) + '/attach', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pdf_b64: b64, job_id: item.active_job_id }) }).then(function () { alert('已挂接 PDF，精读继续'); selectPaper(id); }).catch(function (e) { alert(e.message); });
        };
        reader.readAsDataURL(file);
      });
      if (needsPdf) actions.appendChild(btn('挂接本地PDF', function () { fileInput.click(); }));
      actions.appendChild(btn('导出图表', function () {
        api('/sr/api/paper/' + encodeURIComponent(id) + '/export', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }).then(function () { alert('图表已导出'); }).catch(function (e) { alert(e.message); });
      }));
      box.appendChild(fileInput);
      // 笔记链接
      if (data.outputs && data.outputs.indexOf('reading/quick_read.md') !== -1) {
        var link = el('a', 'sr-link', '打开浅读笔记');
        link.href = '/sr/reading/' + encodeURIComponent(id);
        link.target = '_blank';
        box.appendChild(link);
      }
      if (item.full_read_status === '精读完成') {
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
      body.style.cssText = 'display:flex;gap:8px;flex:1;min-height:0;padding-top:8px;overflow:auto';
      // 左栏：搜索/筛选
      var left = el('div', 'sr-left');
      left.style.cssText = 'width:160px;flex-shrink:0;border-right:1px solid #ddd;padding-right:8px;overflow:auto';
      left.appendChild(el('div', 'sr-dim', '筛选'));
      var searchInput = document.createElement('input');
      searchInput.placeholder = '搜索标题/DOI';
      searchInput.style.cssText = 'width:100%;padding:4px 6px;margin:4px 0 8px;border:1px solid #bbb;border-radius:4px';
      searchInput.addEventListener('input', function () { state.search = searchInput.value; renderTable(); });
      left.appendChild(searchInput);
      state.countLabel = el('div', 'sr-dim', '全部文献（' + state.papers.length + '）');
      left.appendChild(state.countLabel);
      body.appendChild(left);
      // 中栏：论文表格
      var mid = el('div', 'sr-mid');
      mid.style.cssText = 'flex:1 1 460px;min-width:420px;overflow:auto';
      var table = document.createElement('table');
      table.style.cssText = 'width:100%;min-width:520px;table-layout:fixed;border-collapse:collapse';
      var colgroup = document.createElement('colgroup');
      ['120px', 'auto', '64px', '190px'].forEach(function (width) { var col = document.createElement('col'); col.style.width = width; colgroup.appendChild(col); });
      table.appendChild(colgroup);
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
      var right = el('div', 'sr-legacy-detail');
      right.style.cssText = 'width:clamp(340px,38%,500px);flex-shrink:0;border-left:1px solid #ddd;padding-left:8px;overflow:auto';
      state.detail = right;
      right.appendChild(el('p', 'sr-dim', '选择左侧论文查看详情'));
      body.appendChild(right);
      root.appendChild(body);
      // 初始加载
      refreshList();
      return root;
    }

    // ── Phase 3 两栏文献导航 ──────────────────────────────────
    function createQueryStore(onChange) {
      var query = { page: 1, page_size: 50, q: '', folder: '', tags: '', status: '', recent_days: '' };
      return {
        get: function () { return Object.assign({}, query); },
        set: function (patch, resetPage) {
          query = Object.assign({}, query, patch);
          query.page_size = Math.min(100, Math.max(1, Number(query.page_size) || 50));
          if (resetPage) query.page = 1;
          onChange(this.get());
        },
      };
    }

    var navState = { items: [], total: 0, folders: [], request: null, status: 'idle' };
    var queryStore = createQueryStore(function () { loadLibrary(); });

    function libraryUrl(query) {
      var params = new URLSearchParams();
      Object.keys(query).forEach(function (key) {
        if (query[key] !== '') params.set(key, String(query[key]));
      });
      return '/sr/api/library?' + params.toString();
    }

    function loadLibrary() {
      if (!navState.tableBody) return Promise.resolve();
      if (navState.request) navState.request.abort();
      navState.request = new AbortController();
      navState.status = 'loading';
      renderNavigationTable();
      return api(libraryUrl(queryStore.get()), { signal: navState.request.signal }).then(function (data) {
        navState.items = data.items || [];
        navState.total = Number(data.total) || 0;
        navState.status = 'ready';
        renderNavigationTable();
      }).catch(function (error) {
        if (error.name === 'AbortError') return;
        navState.status = 'error';
        navState.error = error.message;
        renderNavigationTable();
      });
    }

    function tableMessage(text, cls) {
      var tr = el('tr');
      var td = el('td', cls || 'sr-empty', text);
      td.colSpan = 5;
      tr.appendChild(td);
      return tr;
    }

    function quickLink(label, href) {
      var link = el('a', 'sr-quick', label);
      link.href = href;
      link.target = '_blank';
      link.addEventListener('click', function (event) { event.stopPropagation(); });
      return link;
    }

    function renderNavigationTable() {
      var tbody = navState.tableBody;
      if (!tbody) return;
      tbody.textContent = '';
      if (navState.status === 'loading') { tbody.appendChild(tableMessage('正在加载文献…')); return; }
      if (navState.status === 'error') { tbody.appendChild(tableMessage('加载失败：' + navState.error, 'sr-error')); return; }
      if (!navState.items.length) { tbody.appendChild(tableMessage('没有符合条件的文献')); return; }
      navState.items.forEach(function (paper) {
        var tr = el('tr', 'sr-paper-row');
        var title = el('td', 'sr-paper-title', paper.title || '（无题名）');
        title.title = paper.title || '（无题名）';
        var authorYear = el('td', 'sr-muted', (paper.authors_short || '—') + (paper.year ? ' · ' + paper.year : ''));
        var folder = el('td', 'sr-muted', paper.folder || '待归类');
        var status = el('td');
        status.appendChild(el('span', 'sr-status', paper.full_read_status || paper.abstract_status || '未开始'));
        var entries = el('td', 'sr-entries');
        entries.appendChild(quickLink('摘要', '/sr/api/paper/' + encodeURIComponent(paper.paper_id) + '/abstract'));
        if (paper.has_pdf) entries.appendChild(quickLink('PDF', '/sr/api/paper/' + encodeURIComponent(paper.paper_id) + '/pdf'));
        if (paper.has_reader) entries.appendChild(quickLink('精读', '/sr/reader/' + encodeURIComponent(paper.paper_id)));
        if (paper.feishu_record_url) entries.appendChild(quickLink('飞书', paper.feishu_record_url));
        entries.appendChild(quickLink('资产', '/sr/api/paper/' + encodeURIComponent(paper.paper_id) + '/assets'));
        tr.appendChild(title); tr.appendChild(authorYear); tr.appendChild(folder); tr.appendChild(status); tr.appendChild(entries);
        tr.addEventListener('click', function () { openDrawer(paper); });
        tbody.appendChild(tr);
      });
      var query = queryStore.get();
      navState.pageLabel.textContent = '第 ' + query.page + ' 页 · 共 ' + navState.total + ' 篇';
      navState.prev.disabled = query.page <= 1;
      navState.next.disabled = query.page * query.page_size >= navState.total;
    }

    function openDrawer(paper) {
      navState.drawer.hidden = false;
      navState.drawerTitle.textContent = paper.title || '（无题名）';
      navState.drawerBody.textContent = '详情操作将在下一阶段接入。';
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

    function renderLiterature() {
      var root = el('div', 'sr-root');
      root.style.cssText = '--sr-bg:#f6f3ec;--sr-surface:#fffdf8;--sr-text:#20332f;--sr-muted:#6e7974;--sr-line:#d9ddd6;--sr-accent:#315f70;--sr-highlight-yellow:#ffd84d;--sr-highlight-blue:#3aa7ff;--sr-sidebar-width:240px;--sr-sidebar-width-collapsed:56px';
      var style = document.createElement('style');
      style.textContent = '.sr-root{position:relative;display:grid;grid-template-columns:var(--sr-sidebar-width) minmax(0,1fr);height:100%;min-width:0;min-height:720px;background:var(--sr-bg);color:var(--sr-text);font:13px/1.45 Georgia,"Noto Serif SC",serif;overflow:hidden}.sr-root.sr-collapsed{grid-template-columns:var(--sr-sidebar-width-collapsed) minmax(0,1fr)}.sr-sidebar{border-right:1px solid var(--sr-line);padding:18px 12px;background:#f1eee6;overflow:hidden}.sr-sidebar-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:22px}.sr-brand{font-weight:700;letter-spacing:.08em}.sr-collapsed .sr-brand,.sr-collapsed .sr-nav-label,.sr-collapsed .sr-folder-list{display:none}.sr-toggle,.sr-btn,.sr-nav-item,.sr-quick{border:1px solid var(--sr-line);background:var(--sr-surface);color:var(--sr-text);border-radius:4px;cursor:pointer}.sr-toggle{width:32px;height:32px}.sr-nav-item{display:flex;width:100%;gap:9px;padding:8px;margin:4px 0;text-align:left}.sr-nav-item[aria-current=true]{border-color:var(--sr-accent);box-shadow:inset 3px 0 var(--sr-highlight-yellow)}.sr-folder-title{margin:20px 8px 8px;color:var(--sr-muted);font-size:11px;letter-spacing:.12em}.sr-folder-list{display:flex;flex-direction:column}.sr-main{display:flex;flex-direction:column;min-width:0;padding:22px 24px}.sr-toolbar{display:flex;align-items:end;gap:8px;flex-wrap:wrap;padding-bottom:14px;border-bottom:1px solid var(--sr-line)}.sr-search{flex:1 1 300px;min-width:240px}.sr-search input,.sr-filter select{box-sizing:border-box;width:100%;height:34px;border:1px solid var(--sr-line);border-radius:4px;background:var(--sr-surface);color:var(--sr-text);padding:0 10px}.sr-filter{display:flex;flex-direction:column;gap:3px;color:var(--sr-muted);font-size:11px}.sr-btn{height:34px;padding:0 12px}.sr-btn-primary{background:var(--sr-text);color:var(--sr-surface);border-color:var(--sr-text)}.sr-btn-mark{box-shadow:inset 0 -3px var(--sr-highlight-blue)}.sr-table-wrap{flex:1;min-height:0;overflow:auto;background:var(--sr-surface)}.sr-table{width:100%;min-width:860px;border-collapse:collapse;table-layout:fixed}.sr-table th{text-align:left;padding:11px 12px;position:sticky;top:0;background:var(--sr-surface);border-bottom:1px solid var(--sr-text);font-weight:600}.sr-table td{padding:12px;border-bottom:1px solid var(--sr-line);vertical-align:top}.sr-paper-title{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.sr-muted{color:var(--sr-muted)}.sr-status{white-space:nowrap;border-left:3px solid var(--sr-highlight-blue);padding-left:7px}.sr-entries{display:flex;gap:5px;flex-wrap:wrap}.sr-quick{padding:2px 6px;text-decoration:none}.sr-empty,.sr-error{text-align:center;padding:48px!important;color:var(--sr-muted)}.sr-error{color:#9b3f35}.sr-pagination{display:flex;justify-content:flex-end;align-items:center;gap:10px;padding-top:12px}.sr-drawer{position:absolute;z-index:4;inset:0 0 0 auto;width:min(440px,92%);box-sizing:border-box;padding:24px;background:var(--sr-surface);border-left:1px solid var(--sr-line);box-shadow:-14px 0 30px rgba(32,51,47,.12)}.sr-drawer[hidden]{display:none}.sr-drawer-close{float:right}.sr-drawer h2{margin:42px 0 12px;font-size:21px}';
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
      [['▦', '全部文献', ''], ['◇', '待归类', '__unfiled__']].forEach(function (entry, index) {
        var item = btn('', function () { queryStore.set({ folder: entry[2] }, true); }, 'sr-nav-item');
        item.setAttribute('aria-current', index === 0 ? 'true' : 'false'); item.appendChild(el('span', '', entry[0])); item.appendChild(el('span', 'sr-nav-label', entry[1])); sidebar.appendChild(item);
      });
      sidebar.appendChild(el('div', 'sr-folder-title', '文件夹'));
      var folderList = el('div', 'sr-folder-list'); sidebar.appendChild(folderList); root.appendChild(sidebar);

      var main = el('main', 'sr-main');
      var toolbar = el('div', 'sr-toolbar');
      var search = el('label', 'sr-search');
      var searchInput = document.createElement('input'); searchInput.placeholder = '搜索题名、作者或 DOI';
      var searchTimer = null;
      searchInput.addEventListener('input', function () { clearTimeout(searchTimer); searchTimer = setTimeout(function () { queryStore.set({ q: searchInput.value.trim() }, true); }, 250); });
      search.appendChild(searchInput); toolbar.appendChild(search);
      toolbar.appendChild(btn('添加文献', function () {}, 'sr-btn sr-btn-primary'));
      toolbar.appendChild(btn('批量粘贴', function () {}, 'sr-btn sr-btn-mark'));
      toolbar.appendChild(filterSelect('状态', [['全部', ''], ['精读完成', 'full_read_ready'], ['失败', 'failed']], 'status'));
      toolbar.appendChild(filterSelect('标签', [['全部标签', '']], 'tags'));
      toolbar.appendChild(filterSelect('最近入库', [['不限', ''], ['7 天', '7'], ['30 天', '30']], 'recent_days'));
      main.appendChild(toolbar);
      var tableWrap = el('div', 'sr-table-wrap');
      var table = el('table', 'sr-table');
      var head = el('thead'); var headRow = el('tr');
      ['题名', '作者 / 年份', '归类', '状态', '快捷入口'].forEach(function (label) { headRow.appendChild(el('th', '', label)); });
      head.appendChild(headRow); table.appendChild(head); navState.tableBody = el('tbody'); table.appendChild(navState.tableBody); tableWrap.appendChild(table); main.appendChild(tableWrap);
      var pager = el('div', 'sr-pagination');
      navState.prev = btn('上一页', function () { var q = queryStore.get(); queryStore.set({ page: Math.max(1, q.page - 1) }); });
      navState.pageLabel = el('span', 'sr-muted', '第 1 页');
      navState.next = btn('下一页', function () { var q = queryStore.get(); queryStore.set({ page: q.page + 1 }); });
      pager.appendChild(navState.prev); pager.appendChild(navState.pageLabel); pager.appendChild(navState.next); main.appendChild(pager); root.appendChild(main);

      navState.drawer = el('aside', 'sr-drawer'); navState.drawer.hidden = true;
      navState.drawer.appendChild(btn('关闭', function () { navState.drawer.hidden = true; }, 'sr-btn sr-drawer-close'));
      navState.drawerTitle = el('h2', '', '文献详情'); navState.drawerBody = el('p', 'sr-muted', '详情操作将在下一阶段接入。'); navState.drawer.appendChild(navState.drawerTitle); navState.drawer.appendChild(navState.drawerBody); root.appendChild(navState.drawer);
      api('/sr/api/folders').then(function (data) { navState.folders = data.folders || []; navState.folders.forEach(function (folder) { folderList.appendChild(btn(folder.name || folder, function () { queryStore.set({ folder: folder.id || folder.name || folder }, true); }, 'sr-nav-item')); }); }).catch(function () {});
      loadLibrary();
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
