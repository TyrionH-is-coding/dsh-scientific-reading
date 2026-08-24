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
    function createLiteratureLifecycle(drawerSessions, drawerActions, rowActions) {
      return {
        closeDrawerScope: function () { drawerSessions.close(); drawerActions.close(); },
        dispose: function () { drawerSessions.close(); drawerActions.dispose(); rowActions.dispose(); },
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
      var safeFeishu = validateUrl(String(paper.feishu_record_url || ''));
      var feishuState = paper.feishu_sync_state || 'unconfigured';
      var busy = ['精读排队', '获取 PDF', '解析全文', '翻译与生成', '需要用户处理', 'queued', 'running', 'needs_user', 'waiting_user'].includes(paper.full_read_status);
      var completeWithoutReader = ['精读完成', 'completed', 'full_read_ready'].includes(paper.full_read_status) && !paper.has_reader;
      return {
        quick: { label: '浅读', disabledReason: ['ready', 'completed'].includes(paper.abstract_status) ? '' : '待补摘要' },
        reader: paper.has_reader
          ? { label: '阅读 HTML', href: '/sr/reader/', disabledReason: '' }
          : { label: '开始精读', href: '', disabledReason: completeWithoutReader ? '精读 HTML 待校验' : busy ? '精读已排队或处理中' : '' },
        pdf: { label: 'PDF', href: paper.has_pdf ? '/sr/api/paper/' : '', disabledReason: paper.has_pdf ? '' : '尚无 PDF 原件' },
        feishu: {
          label: feishuState === 'synced' ? '飞书' : feishuState === 'pending' ? '飞书待同步' : '飞书未配置',
          href: feishuState === 'synced' && safeFeishu ? paper.feishu_record_url : '',
          disabledReason: feishuState === 'synced' && !safeFeishu ? '飞书链接无效' : feishuState === 'pending' ? '等待同步' : feishuState === 'synced' ? '' : '飞书未配置',
        },
      };
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
      function institutionDownload(paperId, jobId, identifier) {
        return trackedApi('/sr/api/paper/' + encodeURIComponent(paperId) + '/download', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ job_id: jobId, identifier: identifier }) }).then(function (result) { detailCache.delete(paperId); return result; });
      }
      function attachPdf(paperId, jobId, pdfBase64) {
        return trackedApi('/sr/api/paper/' + encodeURIComponent(paperId) + '/attach', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ job_id: jobId, pdf_b64: pdfBase64 }) }).then(function (result) { detailCache.delete(paperId); return result; });
      }
      return { loadDetail: loadDetail, loadAssets: loadAssets, invalidate: function (paperId) { detailCache.delete(paperId); }, startFullRead: startFullRead, exportAssets: exportAssets, institutionDownload: institutionDownload, attachPdf: attachPdf, close: stop, dispose: function () { disposed = true; stop(); detailCache.clear(); } };
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
      var drawerOpener = null;
      var drawerSessions = createDrawerSessionController();

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
          if (!disposed) patchPaper(paperId, { last_error: label + '失败：' + (error && error.message ? error.message : '请求失败') });
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
        var authors = Array.isArray(item.authors) ? item.authors.join('、') : paper.authors_short || '作者未知';
        controls.drawerBody.appendChild(el('p', 'sr-muted', authors + (item.year || paper.year ? ' · ' + (item.year || paper.year) : '') + (item.journal ? ' · ' + item.journal : '')));
        if (item.doi) controls.drawerBody.appendChild(el('p', 'sr-biblio', 'DOI：' + item.doi));
        if (item.pmid) controls.drawerBody.appendChild(el('p', 'sr-biblio', 'PMID：' + item.pmid));
        if (item.source_url) { var sourceLine = el('p', 'sr-biblio', '来源：'); if (isSafeHttpUrl(item.source_url)) sourceLine.appendChild(entryLink(item.source_url, item.source_url, true)); else sourceLine.appendChild(document.createTextNode(item.source_url)); controls.drawerBody.appendChild(sourceLine); }
        controls.drawerBody.appendChild(el('p', 'sr-biblio', '归类：' + (item.folder_name || paper.folder || '待归类') + '｜标签：' + ((item.tags || paper.tags || []).join('、') || '无')));
        var pairs = pairAbstractParagraphs(abstract.abstract_en, abstract.abstract_zh);
        controls.drawerBody.appendChild(el('h3', '', 'Abstract'));
        if (!pairs.length) controls.drawerBody.appendChild(el('p', 'sr-empty-note', '待补摘要'));
        pairs.forEach(function (pair) { var block = el('section', 'sr-abstract-pair'); if (pair.en) block.appendChild(el('p', 'sr-abstract-en', pair.en)); if (pair.zh) block.appendChild(el('p', 'sr-abstract-zh', pair.zh)); controls.drawerBody.appendChild(block); });
        controls.drawerBody.appendChild(el('p', 'sr-muted', '浅读：' + (abstract.status || paper.abstract_status || '待补摘要') + '｜精读：' + (paper.full_read_status || '未开始') + '｜飞书：' + (paper.feishu_sync_state || '未配置')));
        var failure = abstract.last_error || paper.last_error; if (failure) controls.drawerBody.appendChild(el('p', 'sr-error-note', '失败原因：' + failure));
        var links = el('div', 'sr-drawer-actions'); var model = paperEntryModel(paper, isSafeHttpUrl);
        if (paper.has_pdf) links.appendChild(entryLink('PDF', '/sr/api/paper/' + encodeURIComponent(paper.paper_id) + '/pdf'));
        if (paper.has_reader) links.appendChild(entryLink('阅读 HTML', '/sr/reader/' + encodeURIComponent(paper.paper_id)));
        if (model.feishu.href) links.appendChild(entryLink('飞书', model.feishu.href, true));
        links.appendChild(btn('查看资产目录', function () { drawerActions.loadAssets(paper.paper_id, session); }, 'sr-entry'));
        links.appendChild(btn('整理文章图表', function () { exportPaperAssets(paper.paper_id, session); }, 'sr-entry'));
        if ((payload.detail.outputs || []).includes('reading/quick_read.md')) { var more = document.createElement('details'); more.appendChild(el('summary', '', '更多')); more.appendChild(entryLink('查看历史浅读', '/sr/reading/' + encodeURIComponent(paper.paper_id))); links.appendChild(more); }
        var job = payload.detail.job || {}; var jobDetail = job.detail || {}; var needsPdf = (job.status === 'waiting_user' && jobDetail.reason_code === 'pdf_required') || (paper.needsUser && paper.pdfRequired);
        if (needsPdf) {
          var identifier = item.doi || item.pmid || item.source_url || '';
          var activeJobId = item.active_job_id || paper.active_job_id || '';
          var validActiveJob = /^job_[0-9a-f]{16}$/.test(activeJobId);
          var institution = btn('使用机构浏览器', function () { drawerActions.institutionDownload(paper.paper_id, activeJobId, identifier).then(function () { drawerSessions.guard(session, paper.paper_id, function () { closeDrawer(); refreshPaper(); }); }).catch(function (error) { drawerSessions.guard(session, paper.paper_id, function () { if (error.name !== 'AbortError') controls.drawerBody.appendChild(el('p', 'sr-error-note', '机构获取失败：' + error.message)); }); }); }, 'sr-entry');
          if (!identifier || !validActiveJob) { institution.disabled = true; institution.title = !validActiveJob ? '任务编号无效，请重试精读' : '缺少可用文献标识'; } links.appendChild(institution);
          var uploadLabel = el('label', 'sr-entry', '挂接本地 PDF'); var upload = document.createElement('input'); upload.type = 'file'; upload.accept = 'application/pdf,.pdf'; upload.hidden = true;
          if (!validActiveJob) { upload.disabled = true; uploadLabel.title = '任务编号无效，请重试精读'; uploadLabel.setAttribute('aria-disabled', 'true'); }
          upload.addEventListener('change', function () { var file = upload.files && upload.files[0]; if (!file) return; var reader = new FileReader(); drawerSessions.trackReader(session, paper.paper_id, reader); reader.onload = function () { drawerSessions.guard(session, paper.paper_id, function () { drawerActions.attachPdf(paper.paper_id, activeJobId, String(reader.result).split(',').pop()).then(function () { drawerSessions.guard(session, paper.paper_id, function () { closeDrawer(); refreshPaper(); }); }).catch(function (error) { drawerSessions.guard(session, paper.paper_id, function () { if (error.name !== 'AbortError') controls.drawerBody.appendChild(el('p', 'sr-error-note', '挂接 PDF 失败：' + error.message)); }); }); }); }; reader.onloadend = function () { drawerSessions.releaseReader(reader); }; reader.onerror = function () { drawerSessions.releaseReader(reader); drawerSessions.guard(session, paper.paper_id, function () { controls.drawerBody.appendChild(el('p', 'sr-error-note', '读取 PDF 失败')); }); }; reader.onabort = function () { drawerSessions.releaseReader(reader); }; reader.readAsDataURL(file); });
          uploadLabel.appendChild(upload); links.appendChild(uploadLabel);
        }
        controls.drawerBody.appendChild(links);
      }
      function openDrawer(paper, opener, options) {
        lifecycle.closeDrawerScope(); var session = drawerSessions.open(paper.paper_id); drawerOpener = opener; controls.backdrop.hidden = false; controls.drawer.setAttribute('aria-hidden', 'false'); sidebar.inert = true; main.inert = true; controls.drawerBody.textContent = '正在加载详情…'; controls.drawerClose.focus();
        drawerActions.loadDetail(paper.paper_id).then(function (payload) { drawerSessions.guard(session, paper.paper_id, function () { renderDrawer(paper, payload, session); if (options && options.exportAfter) exportPaperAssets(paper.paper_id, session); }); }).catch(function (error) { drawerSessions.guard(session, paper.paper_id, function () { if (error.name !== 'AbortError') controls.drawerBody.textContent = '详情加载失败：' + error.message; }); });
      }
      function patchPaper(paperId, patch) {
        state.items = state.items.map(function (paper) { return paper.paper_id === paperId ? Object.assign({}, paper, patch) : paper; }); renderNavigationTable();
      }
      function refreshPaper() { loadLibrary(); }
      function showExportAssets(paperId, assets, session) {
        if (!drawerSessions.isCurrent(session, paperId)) return;
        var count = 'Figures ' + (Number(assets.figures) || 0) + '｜Tables ' + (Number(assets.tables) || 0);
        var result = el('div', 'sr-export-result', count); result.appendChild(el('code', '', assets.exports_path || ''));
        if (assets.exports_path && navigator.clipboard) result.appendChild(btn('复制资产路径', function () { navigator.clipboard.writeText(assets.exports_path); }, 'sr-entry'));
        controls.drawerBody.appendChild(result);
      }
      function showExportError(paperId, message, session) { if (drawerSessions.isCurrent(session, paperId)) controls.drawerBody.appendChild(el('p', 'sr-error-note', message === '尚未整理' ? '资产尚未整理' : '资产整理失败：' + message)); }
      function exportPaperAssets(paperId, session) {
        drawerActions.exportAssets(paperId, session).catch(function (error) { if (error.name !== 'AbortError') showExportError(paperId, error.message, session); });
      }

      function tableMessage(text, cls, retry) {
        var tr = el('tr');
        var td = el('td', cls || 'sr-empty');
        td.colSpan = 6;
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
          var selection = el('td'); var checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.setAttribute('aria-label', '选择 ' + (paper.title || '无题名文献')); selection.appendChild(checkbox); tr.appendChild(selection);
          var titleCell = el('td'); var title = btn(paper.title || '（无题名）', function () { openDrawer(paper, title); }, 'sr-paper-title sr-link-button'); title.title = paper.title || '（无题名）'; titleCell.appendChild(title); tr.appendChild(titleCell);
          tr.appendChild(el('td', 'sr-muted', (paper.authors_short || '—') + (paper.year ? ' · ' + paper.year : '')));
          var classification = el('td', 'sr-muted', paper.folder || '待归类'); (paper.tags || []).slice(0, 2).forEach(function (tag) { classification.appendChild(el('span', 'sr-tag', tag)); }); tr.appendChild(classification);
          var status = el('td');
          status.appendChild(el('span', 'sr-status', '浅读 ' + (paper.abstract_status || '待补摘要')));
          status.appendChild(el('span', 'sr-status', '精读 ' + (paper.full_read_status || '未开始')));
          status.appendChild(el('span', 'sr-status', '飞书 ' + (paper.feishu_sync_state || '未配置')));
          tr.appendChild(status);
          var entries = el('td', 'sr-entries'); var model = paperEntryModel(paper, isSafeHttpUrl);
          entries.appendChild(entryButton(model.quick, function () { openDrawer(paper, title); }));
          if (model.reader.href) entries.appendChild(entryLink(model.reader.label, model.reader.href + encodeURIComponent(paper.paper_id)));
          else entries.appendChild(entryButton(model.reader, function () { runUiAction(rowActions.startFullRead(paper.paper_id), '开始精读', paper.paper_id); }));
          entries.appendChild(model.pdf.href ? entryLink('PDF', model.pdf.href + encodeURIComponent(paper.paper_id) + '/pdf') : entryButton(model.pdf));
          entries.appendChild(model.feishu.href ? entryLink(model.feishu.label, model.feishu.href, true) : entryButton(model.feishu));
          var more = document.createElement('details'); var summary = el('summary', '', '更多'); more.appendChild(summary);
          if (paper.last_error) more.appendChild(btn('重试失败任务', function () { runUiAction(rowActions.startFullRead(paper.paper_id), '重试', paper.paper_id); }, 'sr-menu-action'));
          var exportButton = btn('整理文章图表', function () { openDrawer(paper, exportButton, { exportAfter: true }); }, 'sr-menu-action'); more.appendChild(exportButton);
          entries.appendChild(more); tr.appendChild(entries);
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
      var drawerActions = createPaperActionController({ api: api, onPatch: patchPaper, onRefresh: refreshPaper, onAssets: showExportAssets, onAssetsError: showExportError });
      var rowActions = createPaperActionController({ api: api, onPatch: patchPaper, onRefresh: refreshPaper });
      var lifecycle = createLiteratureLifecycle(drawerSessions, drawerActions, rowActions);
      controls.navigation = [];
      var root = el('div', 'sr-root');
      root.style.cssText = '--sr-bg:#f6f3ec;--sr-surface:#fffdf8;--sr-text:#20332f;--sr-muted:#6e7974;--sr-line:#d9ddd6;--sr-accent:#315f70;--sr-highlight-yellow:#ffd84d;--sr-highlight-blue:#3aa7ff;--sr-sidebar-width:240px;--sr-sidebar-width-collapsed:56px';
      var style = document.createElement('style');
      style.textContent = '.sr-root{position:relative;display:grid;grid-template-columns:var(--sr-sidebar-width) minmax(0,1fr);height:100%;min-width:0;min-height:720px;background:var(--sr-bg);color:var(--sr-text);font:13px/1.45 Georgia,"Noto Serif SC",serif;overflow:hidden}.sr-root.sr-collapsed{grid-template-columns:var(--sr-sidebar-width-collapsed) minmax(0,1fr)}.sr-sidebar{border-right:1px solid var(--sr-line);padding:18px 12px;background:#f1eee6;overflow:hidden}.sr-sidebar-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:22px}.sr-brand{font-weight:700;letter-spacing:.08em}.sr-collapsed .sr-brand,.sr-collapsed .sr-nav-label,.sr-collapsed .sr-folder-list{display:none}.sr-toggle,.sr-btn,.sr-nav-item{border:1px solid var(--sr-line);background:var(--sr-surface);color:var(--sr-text);border-radius:4px;cursor:pointer}.sr-toggle{width:32px;height:32px}.sr-nav-item{display:flex;width:100%;gap:9px;padding:8px;margin:4px 0;text-align:left}.sr-nav-item[aria-current=true]{border-color:var(--sr-accent);box-shadow:inset 3px 0 var(--sr-highlight-yellow)}.sr-folder-title{margin:20px 8px 8px;color:var(--sr-muted);font-size:11px;letter-spacing:.12em}.sr-folder-list{display:flex;flex-direction:column}.sr-main{display:flex;flex-direction:column;min-width:0;padding:22px 24px}.sr-toolbar{display:flex;align-items:end;gap:8px;flex-wrap:wrap;padding-bottom:14px;border-bottom:1px solid var(--sr-line)}.sr-search{flex:1 1 300px;min-width:240px}.sr-search input,.sr-filter input,.sr-filter select{box-sizing:border-box;width:100%;height:34px;border:1px solid var(--sr-line);border-radius:4px;background:var(--sr-surface);color:var(--sr-text);padding:0 10px}.sr-filter{display:flex;flex-direction:column;gap:3px;color:var(--sr-muted);font-size:11px}.sr-btn{height:34px;padding:0 12px}.sr-btn-primary{background:var(--sr-text);color:var(--sr-surface);border-color:var(--sr-text)}.sr-btn-mark{box-shadow:inset 0 -3px var(--sr-highlight-blue)}.sr-table-wrap{flex:1;min-height:0;overflow:auto;background:var(--sr-surface)}.sr-table{width:100%;min-width:1080px;border-collapse:collapse;table-layout:fixed}.sr-table th{text-align:left;padding:11px 12px;position:sticky;top:0;background:var(--sr-surface);border-bottom:1px solid var(--sr-text);font-weight:600}.sr-table td{padding:12px;border-bottom:1px solid var(--sr-line);vertical-align:top}.sr-paper-title{font:inherit;font-weight:600;border:0;background:none;color:var(--sr-text);cursor:pointer;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.sr-muted{color:var(--sr-muted)}.sr-tag{display:inline-block;margin:4px 3px 0 0;padding:1px 5px;border:1px solid var(--sr-line);border-radius:3px}.sr-status{display:block;white-space:nowrap;border-left:3px solid var(--sr-highlight-blue);padding-left:7px;margin-bottom:3px}.sr-entries{color:var(--sr-muted)}.sr-entry{display:inline-block;margin:0 5px 5px 0;padding:3px 6px;border:1px solid var(--sr-line);border-radius:3px;background:var(--sr-surface);color:var(--sr-accent);font:inherit;text-decoration:none;cursor:pointer}.sr-entry:disabled{cursor:not-allowed;color:var(--sr-muted)}.sr-menu-action{display:block;border:0;background:none;padding:5px;cursor:pointer}.sr-empty,.sr-error{text-align:center;padding:48px!important;color:var(--sr-muted)}.sr-error{color:#9b3f35}.sr-retry{margin-left:10px}.sr-pagination{display:flex;justify-content:flex-end;align-items:center;gap:10px;padding-top:12px}.sr-drawer-backdrop{position:absolute;z-index:4;inset:0;background:rgba(32,51,47,.24)}.sr-drawer-backdrop[hidden]{display:none}.sr-drawer{position:absolute;inset:0 0 0 auto;width:min(520px,92%);box-sizing:border-box;padding:24px;background:var(--sr-surface);border-left:1px solid var(--sr-line);box-shadow:-14px 0 30px rgba(32,51,47,.12);overflow:auto}.sr-drawer-head{display:flex;justify-content:flex-end}.sr-abstract-pair{padding:8px 0;border-bottom:1px solid var(--sr-line)}.sr-abstract-zh{color:var(--sr-accent)}.sr-error-note{color:#9b3f35}.sr-drawer-actions{margin-top:18px}';
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
      ['', '题名', '作者 / 年份', '归类', '状态', '快捷入口'].forEach(function (label) { headRow.appendChild(el('th', '', label)); });
      head.appendChild(headRow); table.appendChild(head); controls.tableBody = el('tbody'); table.appendChild(controls.tableBody); tableWrap.appendChild(table); main.appendChild(tableWrap);
      var pager = el('div', 'sr-pagination');
      controls.prev = btn('上一页', function () { var q = queryStore.get(); queryStore.set({ page: Math.max(1, q.page - 1) }); });
      controls.pageLabel = el('span', 'sr-muted', '第 1 页');
      controls.next = btn('下一页', function () { var q = queryStore.get(); queryStore.set({ page: q.page + 1 }); });
      pager.appendChild(controls.prev); pager.appendChild(controls.pageLabel); pager.appendChild(controls.next); main.appendChild(pager); root.appendChild(main);
      controls.backdrop = el('div', 'sr-drawer-backdrop'); controls.backdrop.hidden = true; controls.backdrop.addEventListener('click', function (event) { if (event.target === controls.backdrop) closeDrawer(); });
      controls.drawer = el('aside', 'sr-drawer'); controls.drawer.setAttribute('role', 'dialog'); controls.drawer.setAttribute('aria-modal', 'true'); controls.drawer.setAttribute('aria-hidden', 'true'); controls.drawer.setAttribute('aria-label', '文献详情');
      var drawerHead = el('div', 'sr-drawer-head'); controls.drawerClose = btn('关闭', closeDrawer, 'sr-btn'); drawerHead.appendChild(controls.drawerClose); controls.drawer.appendChild(drawerHead); controls.drawerBody = el('div'); controls.drawer.appendChild(controls.drawerBody); controls.backdrop.appendChild(controls.drawer); root.appendChild(controls.backdrop);
      function onKeydown(event) {
        if (controls.backdrop.hidden) return;
        if (event.key === 'Escape') { closeDrawer(); return; }
        if (event.key === 'Tab') { var focusables = Array.from(controls.drawer.querySelectorAll('button:not(:disabled),a[href],input:not(:disabled),summary')).filter(function (node) { return node.offsetParent !== null; }); var next = nextDialogFocus(focusables, document.activeElement, event.shiftKey); if (next) { event.preventDefault(); next.focus(); } }
      }
      document.addEventListener('keydown', onKeydown);

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
          lifecycle.dispose();
          clearTimeout(searchTimer);
          clearTimeout(tagTimer);
          if (request) request.abort();
          document.removeEventListener('keydown', onKeydown);
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
