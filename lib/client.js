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
    // ── Phase 3 两栏文献导航 ──────────────────────────────────
    function renderLiterature() {
      var disposed = false;
      var request = null;
      var requestSequence = 0;
      var searchTimer = null;
      var tagTimer = null;
      var state = { items: [], total: 0, folders: [], status: 'idle', error: '' };
      var controls = {};

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

      function tableMessage(text, cls, retry) {
        var tr = el('tr');
        var td = el('td', cls || 'sr-empty');
        td.colSpan = 5;
        td.appendChild(el('span', '', text));
        if (retry) td.appendChild(btn('重试', loadLibrary, 'sr-btn sr-retry'));
        tr.appendChild(td);
        return tr;
      }

      function renderNavigationTable() {
        if (disposed) return;
        updatePagination();
        controls.tableBody.textContent = '';
        if (state.status === 'loading') { controls.tableBody.appendChild(tableMessage('正在加载文献…')); return; }
        if (state.status === 'error') { controls.tableBody.appendChild(tableMessage('加载失败：' + state.error, 'sr-error', true)); return; }
        if (!state.items.length) { controls.tableBody.appendChild(tableMessage('没有符合条件的文献')); return; }
        state.items.forEach(function (paper) {
          var tr = el('tr', 'sr-paper-row');
          var title = el('td', 'sr-paper-title', paper.title || '（无题名）');
          title.title = paper.title || '（无题名）';
          tr.appendChild(title);
          tr.appendChild(el('td', 'sr-muted', (paper.authors_short || '—') + (paper.year ? ' · ' + paper.year : '')));
          tr.appendChild(el('td', 'sr-muted', paper.folder || '待归类'));
          var status = el('td');
          status.appendChild(el('span', 'sr-status', paper.full_read_status || paper.abstract_status || '未开始'));
          tr.appendChild(status);
          tr.appendChild(el('td', 'sr-entries', '—'));
          controls.tableBody.appendChild(tr);
        });
      }

      function loadLibrary() {
        if (disposed) return Promise.resolve();
        if (request) request.abort();
        request = new AbortController();
        var sequence = ++requestSequence;
        state.status = 'loading';
        renderNavigationTable();
        return api(libraryUrl(queryStore.get()), { signal: request.signal }).then(function (data) {
          if (disposed || sequence !== requestSequence) return;
          state.items = data.items || [];
          state.total = Number(data.total) || 0;
          state.status = 'ready';
          renderNavigationTable();
        }).catch(function (error) {
          if (disposed || sequence !== requestSequence || error.name === 'AbortError') return;
          state.status = 'error';
          state.error = error.message;
          renderNavigationTable();
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

      var queryStore = createQueryStore(loadLibrary);
      controls.navigation = [];
      var root = el('div', 'sr-root');
      root.style.cssText = '--sr-bg:#f6f3ec;--sr-surface:#fffdf8;--sr-text:#20332f;--sr-muted:#6e7974;--sr-line:#d9ddd6;--sr-accent:#315f70;--sr-highlight-yellow:#ffd84d;--sr-highlight-blue:#3aa7ff;--sr-sidebar-width:240px;--sr-sidebar-width-collapsed:56px';
      var style = document.createElement('style');
      style.textContent = '.sr-root{position:relative;display:grid;grid-template-columns:var(--sr-sidebar-width) minmax(0,1fr);height:100%;min-width:0;min-height:720px;background:var(--sr-bg);color:var(--sr-text);font:13px/1.45 Georgia,"Noto Serif SC",serif;overflow:hidden}.sr-root.sr-collapsed{grid-template-columns:var(--sr-sidebar-width-collapsed) minmax(0,1fr)}.sr-sidebar{border-right:1px solid var(--sr-line);padding:18px 12px;background:#f1eee6;overflow:hidden}.sr-sidebar-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:22px}.sr-brand{font-weight:700;letter-spacing:.08em}.sr-collapsed .sr-brand,.sr-collapsed .sr-nav-label,.sr-collapsed .sr-folder-list{display:none}.sr-toggle,.sr-btn,.sr-nav-item{border:1px solid var(--sr-line);background:var(--sr-surface);color:var(--sr-text);border-radius:4px;cursor:pointer}.sr-toggle{width:32px;height:32px}.sr-nav-item{display:flex;width:100%;gap:9px;padding:8px;margin:4px 0;text-align:left}.sr-nav-item[aria-current=true]{border-color:var(--sr-accent);box-shadow:inset 3px 0 var(--sr-highlight-yellow)}.sr-folder-title{margin:20px 8px 8px;color:var(--sr-muted);font-size:11px;letter-spacing:.12em}.sr-folder-list{display:flex;flex-direction:column}.sr-main{display:flex;flex-direction:column;min-width:0;padding:22px 24px}.sr-toolbar{display:flex;align-items:end;gap:8px;flex-wrap:wrap;padding-bottom:14px;border-bottom:1px solid var(--sr-line)}.sr-search{flex:1 1 300px;min-width:240px}.sr-search input,.sr-filter input,.sr-filter select{box-sizing:border-box;width:100%;height:34px;border:1px solid var(--sr-line);border-radius:4px;background:var(--sr-surface);color:var(--sr-text);padding:0 10px}.sr-filter{display:flex;flex-direction:column;gap:3px;color:var(--sr-muted);font-size:11px}.sr-btn{height:34px;padding:0 12px}.sr-btn-primary{background:var(--sr-text);color:var(--sr-surface);border-color:var(--sr-text)}.sr-btn-mark{box-shadow:inset 0 -3px var(--sr-highlight-blue)}.sr-table-wrap{flex:1;min-height:0;overflow:auto;background:var(--sr-surface)}.sr-table{width:100%;min-width:860px;border-collapse:collapse;table-layout:fixed}.sr-table th{text-align:left;padding:11px 12px;position:sticky;top:0;background:var(--sr-surface);border-bottom:1px solid var(--sr-text);font-weight:600}.sr-table td{padding:12px;border-bottom:1px solid var(--sr-line);vertical-align:top}.sr-paper-title{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.sr-muted{color:var(--sr-muted)}.sr-status{white-space:nowrap;border-left:3px solid var(--sr-highlight-blue);padding-left:7px}.sr-entries{color:var(--sr-muted)}.sr-empty,.sr-error{text-align:center;padding:48px!important;color:var(--sr-muted)}.sr-error{color:#9b3f35}.sr-retry{margin-left:10px}.sr-pagination{display:flex;justify-content:flex-end;align-items:center;gap:10px;padding-top:12px}.sr-drawer{position:absolute;z-index:4;inset:0 0 0 auto;width:min(440px,92%);box-sizing:border-box;padding:24px;background:var(--sr-surface);border-left:1px solid var(--sr-line);box-shadow:-14px 0 30px rgba(32,51,47,.12)}.sr-drawer[hidden]{display:none}';
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
      var search = el('label', 'sr-search');
      var searchInput = document.createElement('input'); searchInput.placeholder = '搜索题名、作者或 DOI';
      searchInput.addEventListener('input', function () { clearTimeout(searchTimer); searchTimer = setTimeout(function () { queryStore.set({ q: searchInput.value.trim() }, true); }, 250); });
      search.appendChild(searchInput); toolbar.appendChild(search);
      toolbar.appendChild(btn('添加文献', function () {}, 'sr-btn sr-btn-primary'));
      toolbar.appendChild(btn('批量粘贴', function () {}, 'sr-btn sr-btn-mark'));
      toolbar.appendChild(filterSelect('状态', [['全部', ''], ['精读完成', 'full_read_ready'], ['失败', 'failed']], 'status'));
      var tagWrap = el('label', 'sr-filter'); tagWrap.appendChild(el('span', '', '标签'));
      var tagInput = document.createElement('input'); tagInput.placeholder = '输入标签筛选';
      tagInput.addEventListener('input', function () { clearTimeout(tagTimer); tagTimer = setTimeout(function () { queryStore.set({ tags: tagInput.value.trim() }, true); }, 250); });
      tagWrap.appendChild(tagInput); toolbar.appendChild(tagWrap);
      toolbar.appendChild(filterSelect('最近入库', [['不限', ''], ['7 天', '7'], ['30 天', '30']], 'recent_days'));
      main.appendChild(toolbar);
      var tableWrap = el('div', 'sr-table-wrap');
      var table = el('table', 'sr-table');
      var head = el('thead'); var headRow = el('tr');
      ['题名', '作者 / 年份', '归类', '状态', '快捷入口'].forEach(function (label) { headRow.appendChild(el('th', '', label)); });
      head.appendChild(headRow); table.appendChild(head); controls.tableBody = el('tbody'); table.appendChild(controls.tableBody); tableWrap.appendChild(table); main.appendChild(tableWrap);
      var pager = el('div', 'sr-pagination');
      controls.prev = btn('上一页', function () { var q = queryStore.get(); queryStore.set({ page: Math.max(1, q.page - 1) }); });
      controls.pageLabel = el('span', 'sr-muted', '第 1 页');
      controls.next = btn('下一页', function () { var q = queryStore.get(); queryStore.set({ page: q.page + 1 }); });
      pager.appendChild(controls.prev); pager.appendChild(controls.pageLabel); pager.appendChild(controls.next); main.appendChild(pager); root.appendChild(main);
      var drawer = el('aside', 'sr-drawer'); drawer.hidden = true; drawer.setAttribute('aria-hidden', 'true'); root.appendChild(drawer);

      api('/sr/api/folders').then(function (folders) {
        if (disposed || !Array.isArray(folders)) return;
        state.folders = folders;
        folders.forEach(function (folder) { addNavigationItem(folderList, '□', folder.name, folder.folder_id); });
      }).catch(function () {});
      updateNavigationSelection();
      loadLibrary();
      return {
        root: root,
        dispose: function () {
          clearTimeout(searchTimer);
          clearTimeout(tagTimer);
          if (request) request.abort();
          disposed = true;
          requestSequence += 1;
        },
      };
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
          }, function () {
            var mountController = createMountController(renderLiterature);
            var literatureRef = mountController.ref;
            return { render: function () {
              return React.createElement('div', { ref: literatureRef });
            } };
          });
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
