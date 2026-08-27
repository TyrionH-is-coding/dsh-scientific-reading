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
              var code = result.error === 'batch_operation_failed' ? result.error : 'batch_failed';
              message = '批量失败：' + code + '｜成功 ' + ((summary.created || 0) + (summary.reused || 0)) + '｜待处理 ' + pending + '｜失败 ' + (summary.failed || 0);
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
          ? { label: '打开 PDF', href: '/sr/api/paper/', action: 'open', disabledReason: '' }
          : { label: '获取 PDF', href: '', action: 'download', disabledReason: '' },
        html: paper.has_reader
          ? { label: '打开 HTML', href: '/sr/reader/', action: 'open', disabledReason: '' }
          : { label: '打开 HTML', href: '', action: 'none', disabledReason: '尚未生成精读 HTML' },
        excel: { label: '定位 Excel', href: '', action: 'locate', disabledReason: '' },
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
      var ingestMode = 'single';
      var ingestOpener = null;
      var ingestSubmitting = false;
      var ingestRequest = null;

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
        controls.drawerBody.appendChild(el('p', 'sr-muted', '浅读：' + (abstract.status || paper.abstract_status || '待补摘要') + '｜精读：' + (paper.full_read_status || '未开始')));
        var failure = abstract.last_error || paper.last_error; if (failure) controls.drawerBody.appendChild(el('p', 'sr-error-note', '失败原因：' + failure));
        var links = el('div', 'sr-drawer-actions'); var model = paperEntryModel(paper, isSafeHttpUrl);
        if (paper.has_pdf) links.appendChild(entryLink('PDF', '/sr/api/paper/' + encodeURIComponent(paper.paper_id) + '/pdf'));
        if (paper.has_reader) links.appendChild(entryLink('阅读 HTML', '/sr/reader/' + encodeURIComponent(paper.paper_id)));
        links.appendChild(btn('查看资产目录', function () { drawerActions.loadAssets(paper.paper_id, session); }, 'sr-entry'));
        links.appendChild(btn('整理文章图表', function () { exportPaperAssets(paper.paper_id, session); }, 'sr-entry'));
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
        state.items = state.items.map(function (paper) { return paper.paper_id === paperId ? Object.assign({}, paper, patch) : paper; }); renderNavigationList();
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
            controls.batchNotice.textContent = '已提交 ' + paperIds.length + ' 篇 PDF 获取任务' + (result.parent_job_id ? ' · ' + result.parent_job_id : '') + '。';
            selections.clear(); renderBatchToolbar();
            return result;
          }).catch(function (error) { controls.batchNotice.textContent = 'PDF 获取失败：' + error.message; });
      }

      function locateExcel(paperId) {
        controls.batchNotice.textContent = '正在定位 Excel 记录…';
        return api('/sr/api/excel/locate?paper_id=' + encodeURIComponent(paperId), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
          .then(function () { controls.batchNotice.textContent = '已在 Excel 总表中定位该文献。'; })
          .catch(function (error) { controls.batchNotice.textContent = '定位 Excel 失败：' + error.message; });
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
        content.appendChild(meta); row.appendChild(content);

        var actions = el('div', 'sr-row-actions'); var model = paperEntryModel(paper, isSafeHttpUrl);
        if (model.pdf.href) actions.appendChild(entryLink(model.pdf.label, model.pdf.href + encodeURIComponent(paper.paper_id) + '/pdf'));
        else actions.appendChild(entryButton(model.pdf, function () { requestDownloads([paper.paper_id]); }));
        if (model.html.href) actions.appendChild(entryLink(model.html.label, model.html.href + encodeURIComponent(paper.paper_id)));
        else actions.appendChild(entryButton(model.html));
        actions.appendChild(entryButton(model.excel, function () { locateExcel(paper.paper_id); }));
        row.appendChild(actions);
        return row;
      }

      function renderNavigationList() {
        if (disposed) return;
        updatePagination();
        controls.paperList.textContent = '';
        if (state.status === 'loading') { controls.paperList.appendChild(listMessage('正在加载文献…')); return; }
        if (state.status === 'error') { controls.paperList.appendChild(listMessage('加载失败：' + state.error, 'sr-error', true)); return; }
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
          if (!disposed && error.name !== 'AbortError') controls.ingestStatus.textContent = '添加失败：' + error.message;
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
      root.style.cssText = '--sr-bg:#f5f3ed;--sr-surface:#fffefa;--sr-text:#172a31;--sr-muted:#6a7679;--sr-line:#d9ddd9;--sr-accent:#176da0;--sr-highlight-yellow:#ffd43b;--sr-highlight-blue:#2b9cf0;--sr-sidebar-width:240px;--sr-sidebar-width-collapsed:56px';
      var style = document.createElement('style');
      style.textContent = '.sr-root{position:relative;display:grid;grid-template-columns:var(--sr-sidebar-width) minmax(0,1fr);height:100%;min-width:0;min-height:720px;background:var(--sr-bg);color:var(--sr-text);font:13px/1.45 Inter,"Noto Sans SC",sans-serif;overflow:hidden}.sr-root.sr-collapsed{grid-template-columns:var(--sr-sidebar-width-collapsed) minmax(0,1fr)}.sr-sidebar{border-right:1px solid var(--sr-line);padding:18px 12px;background:#eeece5;overflow:hidden}.sr-sidebar-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:22px}.sr-brand{font:700 15px/1.2 Georgia,"Noto Serif SC",serif;letter-spacing:.08em}.sr-collapsed .sr-brand,.sr-collapsed .sr-nav-label,.sr-collapsed .sr-folder-list{display:none}.sr-toggle,.sr-btn,.sr-nav-item{border:1px solid var(--sr-line);background:var(--sr-surface);color:var(--sr-text);border-radius:6px;cursor:pointer}.sr-toggle{width:32px;height:32px}.sr-nav-item{display:flex;width:100%;gap:9px;padding:8px;margin:4px 0;text-align:left}.sr-nav-item[aria-current=true]{border-color:var(--sr-accent);box-shadow:inset 3px 0 var(--sr-highlight-yellow);color:var(--sr-accent)}.sr-folder-title{margin:20px 8px 8px;color:var(--sr-muted);font-size:11px;letter-spacing:.12em}.sr-folder-list{display:flex;flex-direction:column}.sr-main{display:flex;flex-direction:column;min-width:0;padding:22px 24px}.sr-toolbar{display:flex;align-items:end;gap:8px;flex-wrap:wrap;padding-bottom:14px;border-bottom:1px solid var(--sr-line)}.sr-toolbar[hidden]{display:none}.sr-search{flex:1 1 300px;min-width:220px}.sr-search input,.sr-filter input,.sr-filter select{box-sizing:border-box;width:100%;height:34px;border:1px solid var(--sr-line);border-radius:6px;background:var(--sr-surface);color:var(--sr-text);padding:0 10px}.sr-filter{display:flex;flex-direction:column;gap:3px;color:var(--sr-muted);font-size:11px}.sr-btn{height:34px;padding:0 12px}.sr-btn-primary{background:var(--sr-text);color:var(--sr-surface);border-color:var(--sr-text)}.sr-btn-mark{box-shadow:inset 0 -3px var(--sr-highlight-blue)}.sr-paper-list{flex:1;min-height:0;overflow:auto;background:var(--sr-surface);border:1px solid var(--sr-line);border-radius:8px}.sr-paper-row{display:grid;grid-template-columns:24px minmax(0,1fr) auto;align-items:center;gap:10px;min-height:58px;padding:10px 12px;border-bottom:1px solid var(--sr-line)}.sr-paper-row:last-child{border-bottom:0}.sr-paper-row:hover{background:#f8fbfc}.sr-paper-select{align-self:start;padding-top:3px}.sr-paper-content{min-width:0}.sr-paper-title{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden;padding:0;border:0;background:none;color:var(--sr-text);font:600 14px/1.38 Georgia,"Noto Serif SC",serif;text-align:left;cursor:pointer}.sr-paper-title:hover{color:var(--sr-accent)}.sr-paper-meta{display:flex;align-items:center;gap:6px;min-width:0;margin-top:5px;color:var(--sr-muted);font-size:12px;white-space:nowrap;overflow:hidden}.sr-paper-meta>span:not(.sr-tag):not(.sr-folder-chip):not(.sr-row-failure):not(.sr-row-running):not(.sr-tag-more)+span:not(.sr-tag):before{content:"·";margin-right:6px}.sr-tag,.sr-folder-chip,.sr-tag-more{flex:none;padding:1px 6px;border-radius:999px;background:#eef3f3;color:#56676a;font-size:11px}.sr-folder-chip{background:#fff2b8;color:#665512}.sr-row-failure,.sr-row-running{flex:none;padding-left:7px;border-left:3px solid #ef6a55;color:#9b3f35}.sr-row-running{border-color:var(--sr-highlight-blue);color:var(--sr-accent)}.sr-row-actions{display:flex;justify-content:flex-end;gap:6px}.sr-muted{color:var(--sr-muted)}.sr-entry{display:inline-block;margin:0;padding:5px 8px;border:1px solid var(--sr-line);border-radius:5px;background:var(--sr-surface);color:var(--sr-accent);font:12px/1.2 Inter,"Noto Sans SC",sans-serif;text-decoration:none;white-space:nowrap;cursor:pointer}.sr-entry:hover:not(:disabled){border-color:var(--sr-highlight-blue);background:#f1f9ff}.sr-entry:disabled{cursor:not-allowed;color:#a0a8a7;background:#f4f4f1}.sr-empty,.sr-error{text-align:center;padding:48px!important;color:var(--sr-muted)}.sr-error{color:#9b3f35}.sr-retry{margin-left:10px}.sr-pagination{display:flex;justify-content:flex-end;align-items:center;gap:10px;padding-top:12px}.sr-batch-bar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:10px 0;border-bottom:1px solid var(--sr-line)}.sr-batch-bar[hidden]{display:none}.sr-batch-notice{min-height:20px;padding:5px 0;color:var(--sr-accent);font-size:12px}.sr-drawer-backdrop{position:absolute;z-index:4;inset:0;background:rgba(20,38,45,.3)}.sr-drawer-backdrop[hidden]{display:none}.sr-drawer{position:absolute;inset:0 0 0 auto;width:min(620px,94%);box-sizing:border-box;padding:24px;background:var(--sr-surface);border-left:1px solid var(--sr-line);box-shadow:-14px 0 30px rgba(20,38,45,.14);overflow:auto}.sr-drawer-head{display:flex;justify-content:flex-end}.sr-abstract-pair{padding:10px 0;border-bottom:1px solid var(--sr-line)}.sr-abstract-en{font-family:Georgia,serif}.sr-abstract-zh{color:var(--sr-accent)}.sr-error-note{color:#9b3f35}.sr-drawer-actions{display:flex;gap:6px;margin-top:18px}@media(max-width:900px){.sr-root{grid-template-columns:var(--sr-sidebar-width-collapsed) minmax(0,1fr)}.sr-brand,.sr-nav-label,.sr-folder-list,.sr-folder-title{display:none}.sr-main{padding:14px 12px}.sr-paper-row{grid-template-columns:22px minmax(0,1fr)}.sr-row-actions{grid-column:2;justify-content:flex-start}.sr-paper-meta{max-width:100%}}';
      style.textContent += '.sr-root{height:calc(100vh - 76px);min-height:0;max-height:100%}.sr-btn:disabled{cursor:not-allowed;opacity:.55}.sr-ingest-backdrop{position:absolute;z-index:6;inset:0;display:grid;place-items:center;padding:20px;background:rgba(32,51,47,.24)}.sr-ingest-backdrop[hidden]{display:none}.sr-ingest-dialog{width:min(520px,100%);box-sizing:border-box;padding:24px;background:var(--sr-surface);border:1px solid var(--sr-line);border-radius:6px;box-shadow:0 18px 50px rgba(32,51,47,.2)}.sr-ingest-dialog textarea{box-sizing:border-box;width:100%;resize:vertical;border:1px solid var(--sr-line);border-radius:4px;padding:10px;font:inherit}.sr-ingest-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:14px}.sr-ingest-status{min-height:1.5em;color:var(--sr-accent)}';
      style.textContent += '.sr-main{min-height:0;overflow:hidden}';
      style.textContent += '.sr-main{padding-bottom:126px}';
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
      var searchInput = document.createElement('input'); searchInput.placeholder = '搜索题名、作者或 DOI';
      searchInput.addEventListener('input', function () { clearTimeout(searchTimer); searchTimer = setTimeout(function () { queryStore.set({ q: searchInput.value.trim() }, true); }, 250); });
      search.appendChild(searchInput); toolbar.appendChild(search);
      var addPaperButton = btn('添加文献', function () { openIngestDialog('single', addPaperButton); }, 'sr-btn sr-btn-primary'); toolbar.appendChild(addPaperButton);
      var batchPasteButton = btn('批量粘贴', function () { openIngestDialog('batch', batchPasteButton); }, 'sr-btn sr-btn-mark'); toolbar.appendChild(batchPasteButton);
      toolbar.appendChild(filterSelect('状态', [['全部', ''], ['精读完成', 'full_read_ready'], ['失败', 'failed']], 'status'));
      var tagWrap = el('label', 'sr-filter'); tagWrap.appendChild(el('span', '', '标签'));
      var tagInput = document.createElement('input'); tagInput.placeholder = '输入标签筛选';
      tagInput.addEventListener('input', function () { clearTimeout(tagTimer); tagTimer = setTimeout(function () { queryStore.set({ tags: tagInput.value.trim() }, true); }, 250); });
      tagWrap.appendChild(tagInput); toolbar.appendChild(tagWrap);
      toolbar.appendChild(filterSelect('最近入库', [['不限', ''], ['7 天', '7'], ['30 天', '30']], 'recent_days'));
      main.appendChild(toolbar);
      controls.batchBar = el('div', 'sr-batch-bar'); controls.batchBar.hidden = true;
      controls.batchCount = el('strong', '', '已选 0 篇'); controls.batchBar.appendChild(controls.batchCount);
      function submitBatch(action, payload) { return batchActions.submit(action, payload).catch(function (error) { if (error.name !== 'AbortError') controls.batchNotice.textContent = '批量操作失败：' + error.message; }); }
      controls.batchBar.appendChild(btn('下载缺失 PDF', function () { requestDownloads(selections.values()); }, 'sr-btn sr-btn-primary'));
      controls.batchBar.appendChild(btn('移动文件夹', function () { var folderId = window.prompt('输入目标文件夹 ID；留空移到待归类', '') || null; submitBatch('move_folder', { folder_id: folderId }); }, 'sr-btn'));
      controls.batchBar.appendChild(btn('添加标签', function () { var value = window.prompt('输入标签，多个标签用逗号分隔', ''); if (value) submitBatch('add_tags', { tags: value.split(',').map(function (tag) { return tag.trim(); }).filter(Boolean) }); }, 'sr-btn'));
      controls.batchBar.appendChild(btn('移除标签', function () { var value = window.prompt('输入要移除的标签，多个标签用逗号分隔', ''); if (value) submitBatch('remove_tags', { tags: value.split(',').map(function (tag) { return tag.trim(); }).filter(Boolean) }); }, 'sr-btn'));
      controls.batchBar.appendChild(btn('取消选择', function () { selections.clear(); renderBatchToolbar(); renderNavigationList(); }, 'sr-btn'));
      main.appendChild(controls.batchBar);
      controls.batchNotice = el('div', 'sr-batch-notice'); controls.batchNotice.setAttribute('role', 'status'); controls.batchNotice.setAttribute('aria-live', 'polite'); main.appendChild(controls.batchNotice);
      function renderBatchToolbar() { var count = selections.size(); controls.batchBar.hidden = count === 0; controls.toolbar.hidden = count > 0; controls.batchCount.textContent = '已选 ' + count + ' 篇'; }
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

      api('/sr/api/folders').then(function (folders) {
        if (disposed || !Array.isArray(folders)) return;
        state.folders = folders;
        folders.forEach(function (folder) { addNavigationItem(folderList, '□', folder.name, folder.folder_id); });
      }).catch(function () {});
      updateNavigationSelection();
      loadLibrary();
      var onboardingMount = null;
      api('/sr/api/settings/status').then(function (snapshot) {
        if (disposed || !snapshot.onboarding || !snapshot.onboarding.show_settings) return;
        onboardingMount = renderSettingsStatus(snapshot, function () {
          if (!onboardingMount) return;
          onboardingMount.dispose(); onboardingMount.root.remove(); onboardingMount = null;
        });
        onboardingMount.root.classList.add('sr-settings-onboarding');
        root.appendChild(onboardingMount.root);
        return api('/sr/api/settings/mark-presented', { method: 'POST', headers: { 'Content-Type': 'application/json', 'x-sr-csrf': '1' }, body: JSON.stringify({ version: 'v1' }) });
      }).catch(function () {});
      return {
        root: root,
        dispose: function () {
          lifecycle.dispose();
          batchActions.dispose();
          clearTimeout(searchTimer);
          clearTimeout(tagTimer);
          if (request) request.abort();
          if (ingestRequest) ingestRequest.abort();
          if (onboardingMount) onboardingMount.dispose();
          document.removeEventListener('keydown', onKeydown);
          disposed = true;
          requestSequence += 1;
        },
      };
    }

    function renderSettingsStatus(initialSnapshot, onContinue) {
      var disposed = false;
      var active = null;
      var root = el('div', 'sr-settings-page');
      var style = document.createElement('style');
      style.textContent = '.sr-settings-page{box-sizing:border-box;height:calc(100vh - 76px);overflow:auto;padding:32px clamp(18px,5vw,68px) 126px;background:#f5f3ed;color:#172a31;font:13px/1.5 Inter,"Noto Sans SC",sans-serif}.sr-settings-onboarding{position:absolute;z-index:8;inset:0;height:100%}.sr-settings-shell{max-width:1040px;margin:0 auto}.sr-settings-head{display:flex;align-items:end;justify-content:space-between;gap:20px;margin-bottom:24px;padding-bottom:16px;border-bottom:1px solid #cfd7d5}.sr-settings-head h1{margin:0 0 6px;font:700 30px/1.15 Georgia,"Noto Serif SC",serif}.sr-settings-head p{margin:0;color:#687579}.sr-settings-head-actions{display:flex;gap:8px}.sr-settings-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.sr-settings-panel{min-height:128px;padding:18px;border:1px solid #d7ddda;border-radius:9px;background:#fffefa;box-shadow:0 3px 14px rgba(23,42,49,.04)}.sr-settings-panel h2{margin:0 0 9px;font:650 15px/1.3 Georgia,"Noto Serif SC",serif}.sr-settings-state{display:inline-flex;align-items:center;gap:7px;color:#176da0}.sr-settings-state:before{content:"";width:8px;height:8px;border-radius:50%;background:#2b9cf0}.sr-settings-detail{margin:9px 0 0;color:#687579}.sr-key-form{display:flex;gap:7px;margin-top:12px}.sr-key-form input{min-width:0;flex:1;height:34px;box-sizing:border-box;border:1px solid #d7ddda;border-radius:6px;padding:0 9px;background:#fff}.sr-settings-page button{height:34px;border:1px solid #cfd7d5;border-radius:6px;padding:0 12px;background:#fffefa;color:#172a31;cursor:pointer}.sr-settings-page button:hover{border-color:#2b9cf0}.sr-settings-primary{background:#172a31!important;color:#fff!important;border-color:#172a31!important}.sr-settings-note{min-height:20px;color:#176da0}.sr-settings-footnote{margin-top:20px;padding-left:10px;border-left:3px solid #ffd43b;color:#687579}@media(max-width:760px){.sr-settings-head{align-items:start;flex-direction:column}.sr-settings-grid{grid-template-columns:1fr}.sr-key-form{flex-wrap:wrap}}';
      root.appendChild(style);
      var shell = el('div', 'sr-settings-shell'); root.appendChild(shell);
      var head = el('header', 'sr-settings-head'); var heading = el('div'); heading.appendChild(el('h1', '', '设置与状态')); heading.appendChild(el('p', '', '这里仅显示环境能力。检测由你手动触发，不会在后台反复扫描。')); head.appendChild(heading);
      var headActions = el('div', 'sr-settings-head-actions');
      var recheck = btn('重新检测', function () { recheck.disabled = true; write('/sr/api/settings/recheck', 'POST', { targets: ['download', 'institution', 'mineru_local', 'mineru_api', 'cloak'] }).then(renderSnapshot).catch(showError).finally(function () { recheck.disabled = false; }); }, 'sr-settings-primary'); headActions.appendChild(recheck);
      if (onContinue) headActions.appendChild(btn('进入文献库', onContinue));
      head.appendChild(headActions); shell.appendChild(head);
      var notice = el('div', 'sr-settings-note'); notice.setAttribute('role', 'status'); notice.setAttribute('aria-live', 'polite'); shell.appendChild(notice);
      var grid = el('div', 'sr-settings-grid'); shell.appendChild(grid);

      function statusText(value) {
        var labels = { ready: '可用', configured: '已配置', logged_in: '已登录', installed: '已安装', not_installed: '未安装（正常）', empty: '尚无文献', not_checked: '尚未检测', not_configured: '未配置', unavailable: '不可用', failed: '检测失败' };
        return labels[value] || value || '未知';
      }
      function panel(title, status, detail, extra) {
        var card = el('section', 'sr-settings-panel'); card.appendChild(el('h2', '', title)); card.appendChild(el('div', 'sr-settings-state', statusText(status))); card.appendChild(el('p', 'sr-settings-detail', detail)); if (extra) card.appendChild(extra); grid.appendChild(card);
      }
      function renderSnapshot(snapshot) {
        if (disposed) return;
        grid.textContent = '';
        var institution = snapshot.institution || {}; var download = snapshot.download || {}; var mineru = snapshot.mineru || {}; var local = mineru.local || {}; var apiStatus = mineru.api || {}; var library = snapshot.library || {}; var cloak = snapshot.cloak || {};
        panel('机构访问', institution.status, institution.school ? '当前机构：' + institution.school : '尚未选择机构；需要时可在插件基础设置中填写。');
        panel('PDF 下载', download.status, '优先开放获取与直接下载，必要时复用系统 Chrome 的机构登录。');
        var keyForm = el('div', 'sr-key-form'); var keyInput = document.createElement('input'); keyInput.type = 'password'; keyInput.placeholder = '粘贴 MinerU API Key'; keyInput.autocomplete = 'off'; keyForm.appendChild(keyInput);
        keyForm.appendChild(btn('保存密钥', function () { var value = keyInput.value.trim(); keyInput.value = ''; if (!value) return; write('/sr/api/settings/mineru-key', 'POST', { api_key: value }).then(function () { notice.textContent = 'MinerU API Key 已安全保存。'; return load(); }).catch(showError); }));
        keyForm.appendChild(btn('删除密钥', function () { keyInput.value = ''; write('/sr/api/settings/mineru-key', 'DELETE').then(function () { notice.textContent = 'MinerU API Key 已删除。'; return load(); }).catch(showError); }));
        panel('全文解析', local.status === 'ready' ? 'ready' : apiStatus.status, '本机 MinerU：' + statusText(local.status) + ' · API：' + statusText(apiStatus.status) + '。自动模式优先使用已验证的本机 MinerU。', keyForm);
        panel('本地文献库', library.status, 'SQLite 文献 ' + (Number(library.papers) || 0) + ' 篇 · Excel 待同步 ' + (Number(library.xlsx_pending) || 0) + ' 篇。');
        panel('CloakBrowser', cloak.status, '默认不安装。仅在明确遇到反自动化拦截时，作为可选增强包提示。');
        notice.textContent = '状态已更新。';
      }
      function write(path, method, body) { return api(path, { method: method, headers: { 'Content-Type': 'application/json', 'x-sr-csrf': '1' }, body: method === 'DELETE' ? undefined : JSON.stringify(body || {}) }); }
      function showError(error) { if (!disposed) notice.textContent = '操作失败：' + (error && error.message ? error.message : '请求失败'); }
      function load() { if (active) active.abort(); active = new AbortController(); return api('/sr/api/settings/status', { signal: active.signal }).then(renderSnapshot).catch(function (error) { if (error.name !== 'AbortError') showError(error); }); }
      if (initialSnapshot) renderSnapshot(initialSnapshot); else load();
      shell.appendChild(el('p', 'sr-settings-footnote', '密钥使用 Windows DPAPI 加密后仅保存在本机；解析时论文 PDF 会发送至所选 MinerU API。'));
      return { root: root, dispose: function () { disposed = true; if (active) active.abort(); } };
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
      var mineruNote = el('div', 'sr-dim', '完整环境状态与 MinerU 密钥管理请前往“设置与状态”页。密钥由 Windows DPAPI 加密并仅保存在本机。');
      mineruNote.style.cssText = 'font-size:11px;line-height:1.55;color:var(--dsw-alias-label-tertiary,#777);padding:8px 10px;border-radius:6px;background:var(--dsw-alias-bg-layer-2,#f5f5f3)';
      root.appendChild(mineruNote);
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
        return ctx.slots.inject('conversation.view', function () {
          return ctx.slots.register({
            name: 'conversation.view',
            id: 'scientific-reading-settings',
            order: 21,
            label: function () { return '设置与状态'; },
          }, function () {
            var mountController = createMountController(renderSettingsStatus);
            var settingsRef = mountController.ref;
            return { render: function () { return React.createElement('div', { ref: settingsRef }); } };
          });
        });
      }, 'sr-settings-status-tab');
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
