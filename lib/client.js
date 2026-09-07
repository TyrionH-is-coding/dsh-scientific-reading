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
    function searchMatchModel(match) {
      if (!match || typeof match !== 'object' || typeof match.snippet !== 'string' || !match.snippet.trim()) return null;
      var kindLabels = { metadata: '元数据', abstract_en: '英文摘要', abstract_zh: '中文摘要', conclusion: '已确认结论', personal: '个人记录' };
      if (!Object.prototype.hasOwnProperty.call(kindLabels, match.content_type)) return null;
      var model = { kind: match.content_type, kindLabel: kindLabels[match.content_type], snippet: match.snippet.trim(), basisLabel: '', evidenceLabel: '', validityLabel: '', evidenceHref: '' };
      if (match.content_type !== 'conclusion') return model;
      var basisLabels = { paper: '论文定位', personal: '个人判断', inference: '推断', question: '待核问题', legacy: '旧版记录' };
      var evidenceLabels = { location_verified: '定位有效', stale: '定位失效', legacy_unverified: '旧版未验证', not_provided: '未提供定位' };
      model.basisLabel = Object.prototype.hasOwnProperty.call(basisLabels, match.basis) ? basisLabels[match.basis] : '未标注';
      model.evidenceLabel = Object.prototype.hasOwnProperty.call(evidenceLabels, match.evidence_status) ? evidenceLabels[match.evidence_status] : '定位状态未知';
      model.validityLabel = match.scientific_validity === 'not_assessed' ? '科学有效性未评估' : '科学有效性状态未知';
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
          var link = el('a', 'sr-search-evidence', '查看已验证定位');
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
    function renderLiterature(sessions, openModels) {
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
      var reviewSessions = createReviewSessionController({ sessions: sessions, api: api });

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
        if (paper.has_pdf) links.appendChild(entryLink('PDF', '/sr/api/paper/' + encodeURIComponent(paper.paper_id) + '/pdf', true));
        if (paper.has_reader) links.appendChild(entryLink('阅读 HTML', '/sr/reader/' + encodeURIComponent(paper.paper_id)));
        links.appendChild(btn('查看资产目录', function () { drawerActions.loadAssets(paper.paper_id, session); }, 'sr-entry'));
        links.appendChild(btn('整理文章图表', function () { exportPaperAssets(paper.paper_id, session); }, 'sr-entry'));
        var job = payload.detail.job || {}; var jobDetail = job.detail || {}; var needsPdf = (job.status === 'waiting_user' && jobDetail.reason_code === 'pdf_required') || (paper.needsUser && paper.pdfRequired);
        if (needsPdf) {
          var identifier = item.doi || item.pmid || item.source_url || '';
          var activeJobId = item.active_job_id || paper.active_job_id || '';
          var validActiveJob = /^job_[0-9a-f]{16}$/.test(activeJobId);
          var oaRetry = btn('重试 OA 获取', function () { drawerActions.oaDownload(paper.paper_id, activeJobId, identifier).then(function () { drawerSessions.guard(session, paper.paper_id, function () { closeDrawer(); refreshPaper(); }); }).catch(function (error) { drawerSessions.guard(session, paper.paper_id, function () { if (error.name !== 'AbortError') controls.drawerBody.appendChild(el('p', 'sr-error-note', 'OA 获取失败：' + error.message)); }); }); }, 'sr-entry');
          if (!identifier || !validActiveJob) { oaRetry.disabled = true; oaRetry.title = !validActiveJob ? '任务编号无效，请重试精读' : '缺少可用文献标识'; } links.appendChild(oaRetry);
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
          .then(function (result) { controls.batchNotice.textContent = result.selected ? '已在 Excel 总表中定位该文献。' : '已打开文献总表，请按论文名查找对应记录。'; })
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
        content.appendChild(meta);
        var searchMatches = renderSearchMatches(paper); if (searchMatches) content.appendChild(searchMatches);
        row.appendChild(content);

        var actions = el('div', 'sr-row-actions'); var model = paperEntryModel(paper, isSafeHttpUrl);
        if (model.pdf.href) actions.appendChild(entryLink(model.pdf.label, model.pdf.href + encodeURIComponent(paper.paper_id) + '/pdf', model.pdf.external));
        else actions.appendChild(entryButton(model.pdf, function () { requestDownloads([paper.paper_id]); }));
        if (model.html.href) actions.appendChild(entryLink(model.html.label, model.html.href + encodeURIComponent(paper.paper_id)));
        else actions.appendChild(entryButton(model.html));
        var reviewButton = entryButton({ label: '整理入库' }, function () {
          reviewButton.disabled = true;
          controls.batchNotice.textContent = '正在打开论文整理会话…';
          reviewSessions.open(paper.paper_id).then(function () {
            controls.batchNotice.textContent = '已打开“' + (paper.title || '无题名文献') + '”整理会话。';
          }).catch(function (error) {
            controls.batchNotice.textContent = '整理会话打开失败：' + (error && error.message ? error.message : '请求失败');
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
      style.textContent += '.sr-search-scope{display:block;margin-top:3px;color:var(--sr-muted);font-size:10px}.sr-search-matches{display:grid;gap:5px;margin-top:8px}.sr-search-match{padding:7px 9px;border-left:3px solid var(--sr-highlight-blue);border-radius:0 5px 5px 0;background:#f5f8f8}.sr-search-match-head{display:flex;align-items:center;gap:5px;flex-wrap:wrap}.sr-search-kind,.sr-search-basis,.sr-search-evidence-status,.sr-search-validity{padding:1px 5px;border-radius:999px;background:#e8eeee;color:#506165;font-size:10px}.sr-search-kind{background:#e5f2fb;color:var(--sr-accent)}.sr-search-validity{background:#f4f1e8}.sr-search-snippet{margin:4px 0 0;color:var(--sr-text);font-size:12px;white-space:normal;overflow-wrap:anywhere}.sr-search-evidence{display:inline-block;margin-top:4px;color:var(--sr-accent);font-size:11px}';
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
      search.appendChild(searchInput); search.appendChild(el('span', 'sr-search-scope', '范围：元数据、英中摘要与已确认结论')); toolbar.appendChild(search);
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
        }, openModels);
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
          reviewSessions.dispose();
          document.removeEventListener('keydown', onKeydown);
          disposed = true;
          requestSequence += 1;
        },
      };
    }

    function renderSettingsStatus(initialSnapshot, onContinue, openModels) {
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
        '.sr-settings-onboarding{position:absolute;z-index:8;inset:0;height:100%;min-height:0;overflow:auto}.sr-settings-shell{max-width:900px;margin:0 auto}.sr-settings-head{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:8px}.sr-settings-head h1{margin:0 0 6px;font-size:24px;font-weight:650;letter-spacing:-.5px}.sr-settings-head p{margin:0;color:var(--sr-muted);font-size:13px}',
        '.sr-settings-group{margin-top:28px}.sr-settings-group h2{margin:0;padding-bottom:10px;border-bottom:1px solid var(--sr-line);font-size:13px;font-weight:600;color:var(--sr-muted)}.sr-setting-row{display:grid;grid-template-columns:minmax(180px,1fr) minmax(200px,1.25fr);align-items:center;gap:24px;padding:17px 0;border-bottom:1px solid var(--sr-line)}.sr-setting-row:last-child{border-bottom:0}.sr-setting-label{font-weight:550}.sr-setting-description{margin:4px 0 0;font-size:12px;color:var(--sr-muted);max-width:370px}.sr-setting-control{display:flex;justify-content:flex-end;align-items:center;gap:10px;flex-wrap:wrap;min-width:0}.sr-setting-value{font-variant-numeric:tabular-nums}.sr-setting-path{flex:1;min-width:0;overflow-wrap:anywhere;font-size:12px;text-align:right}',
        '.sr-settings-state{font-size:12px;color:var(--sr-muted)}.sr-settings-state[data-state="configured"],.sr-settings-state[data-state="authenticated"],.sr-settings-state[data-state="ready"]{color:#248467}.sr-key-form{width:100%;display:flex;gap:8px;flex-wrap:wrap}.sr-key-form input{flex:1;min-width:130px;width:0;height:36px;box-sizing:border-box;border:1px solid var(--sr-line);border-radius:7px;padding:0 10px;background:var(--sr-bg);color:var(--sr-text);font:inherit}.sr-key-meta{width:100%;display:flex;align-items:center;justify-content:space-between}',
        '.sr-settings-page button,.sr-settings-link{display:inline-flex;align-items:center;justify-content:center;box-sizing:border-box;min-height:34px;border:1px solid var(--sr-line);border-radius:7px;padding:5px 12px;background:var(--sr-bg);color:var(--sr-text);font:inherit;font-size:12px;cursor:pointer;text-decoration:none}.sr-settings-page button:hover,.sr-settings-link:hover{background:var(--dsw-alias-interactive-bg-hover,#f4f5f7)}.sr-settings-page button:disabled{cursor:wait;opacity:.5}.sr-settings-primary{background:#3564df!important;color:#fff!important;border-color:#3564df!important}.sr-settings-page .sr-settings-secondary{border:0;color:var(--sr-muted);padding:0;min-height:24px}.sr-settings-page :focus-visible{outline:2px solid #3564df;outline-offset:3px}',
        '.sr-settings-note{font-size:12px;color:var(--sr-muted)}.sr-settings-note:empty{display:none}.sr-settings-note:not(:empty){margin-top:12px}.sr-settings-details summary{cursor:pointer;color:var(--sr-muted);font-size:12px;padding:12px 0}.sr-settings-details .sr-setting-row{padding:11px 0}.sr-settings-footnote{margin-top:26px;font-size:11px;color:var(--sr-muted)}',
        '@container(max-width:590px){.sr-setting-row{grid-template-columns:1fr;gap:10px}.sr-setting-control{justify-content:flex-start}.sr-setting-path{text-align:left}.sr-settings-head{align-items:start}.sr-settings-head h1{font-size:21px}}',
      ].join('');
      root.appendChild(style);
      var shell = el('div', 'sr-settings-shell'); root.appendChild(shell);
      var head = el('header', 'sr-settings-head'); var heading = el('div'); heading.appendChild(el('h1', '', '设置与状态')); heading.appendChild(el('p', '', '连接模型与解析服务，管理文献库。')); head.appendChild(heading);
      var headActions = el('div', 'sr-settings-head-actions');
      if (onContinue) headActions.appendChild(btn('进入文献库', onContinue));
      head.appendChild(headActions); shell.appendChild(head);
      var notice = el('div', 'sr-settings-note'); notice.setAttribute('role', 'status'); notice.setAttribute('aria-live', 'polite'); shell.appendChild(notice);
      var groups = el('div', 'sr-settings-groups'); shell.appendChild(groups);

      function statusText(value) {
        var labels = { authenticated: '已登录', unauthenticated: '未登录', unsupported_auth: '需要登录 Codex 订阅', ready: '可用', configured: '已配置', logged_in: '已登录', valid: '已连接', none: '未登录', expired: '需要重新认证', unreachable: '暂时无法检测', installed: '已安装', not_installed: '未安装', empty: '尚无文献', not_checked: '尚未检测', not_configured: '未配置', unavailable: '暂不可用', failed: '检测失败' };
        return labels[value] || value || '未知';
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
        var modelButton = btn('打开 DSH 模型设置', function () { if (openModels) Promise.resolve().then(openModels).catch(showError); });
        modelButton.disabled = !openModels;
        row(models, '翻译与导读模型', '在 DSH 模型设置中配置服务，再从会话中选择使用的模型。', modelButton);
        if (identity) {
          var oauth = row(models, 'Codex 订阅', '此登录仅用于当前独立工作台。也可使用 DSH 中配置的模型 API。', stateLabel(oauthState ? oauthState.status : 'not_checked'));
          var loginLink = el('a', 'sr-settings-link', oauthState && oauthState.authenticated ? '管理登录' : '连接 Codex');
          loginLink.href = '/api/codex-oauth/ui'; loginLink.target = '_blank'; loginLink.rel = 'noopener'; oauth.appendChild(loginLink);
        }
        var parsing = group('PDF 解析');
        var keyForm = el('div', 'sr-key-form'); var keyInput = document.createElement('input'); keyInput.type = 'password'; keyInput.placeholder = '粘贴 MinerU API Key'; keyInput.autocomplete = 'off'; keyForm.appendChild(keyInput);
        keyInput.setAttribute('aria-label', 'MinerU API Key'); keyInput.value = draftKey;
        function keyAction(button, token) {
          keyInput.value = ''; button.disabled = true;
          updateMineruKey(api, token).then(function (next) { renderSnapshot(next); notice.textContent = token === null ? 'MinerU API Key 已删除。' : 'MinerU API Key 已安全保存；尚未进行真实 API 调用。'; }).catch(showError).finally(function () { button.disabled = false; });
        }
        var saveKey = btn(apiStatus.status === 'configured' ? '替换密钥' : '保存密钥', function () {
          var token = keyInput.value.trim(); if (!token) { keyInput.focus(); return; } keyAction(saveKey, token);
        }, 'sr-settings-primary'); keyForm.appendChild(saveKey);
        var keyMeta = el('div', 'sr-key-meta'); keyMeta.appendChild(stateLabel(apiStatus.status)); keyForm.appendChild(keyMeta);
        if (apiStatus.status === 'configured') {
          var deleteKey = btn('删除密钥', function () { keyAction(deleteKey, null); }, 'sr-settings-secondary'); keyMeta.appendChild(deleteKey);
        }
        row(parsing, 'MinerU API Key', '用于全文解析。已配置不代表 API 已完成真实调用。', keyForm);
        var libraryGroup = group('文献库');
        row(libraryGroup, '本地文献库', '已入库的论文与个人阅读记录。', (Number(library.papers) || 0) + ' 篇文献');
        row(libraryGroup, 'Excel 待同步', '保存并关闭工作簿后，可从文献页或 Codex 继续同步。', (Number(library.xlsx_pending) || 0) + ' 篇');
        var location = row(libraryGroup, '存储位置', 'PDF、阅读成果及文献库保存在此目录。');
        location.appendChild(el('span', 'sr-setting-path', library.data_root || '资产位置暂不可用'));
        if (library.data_root) location.appendChild(btn('复制路径', function () {
          Promise.resolve().then(function () { return navigator.clipboard.writeText(library.data_root); }).then(function () { notice.textContent = '文献库路径已复制。'; }).catch(showError);
        }));
        var about = group('关于');
        row(about, identity ? 'Deep Literature for Codex' : 'DSH Scientific Reading', '', identity ? identity.version : (versions.plugin || '版本暂不可用'));
        var details = el('details', 'sr-settings-details'); details.open = detailsOpen; details.appendChild(el('summary', '', '版本与环境状态')); about.appendChild(details);
        row(details, '文献引擎', '', snapshot.engine_version || '版本暂不可用');
        row(details, '文献插件', '', versions.plugin || '版本暂不可用');
        row(details, 'DSH', '', (identity && identity.dshVersion) || versions.dsh || '版本暂不可用');
        row(details, 'OA 自动获取', '仅尝试开放获取全文；未取得时可补入本地 PDF。', stateLabel(download.status));
        row(details, '本机 MinerU', '未安装时可使用上方配置的 MinerU API。', stateLabel(local.status));
        var recheck = btn('重新检测', function () {
          recheck.disabled = true;
          Promise.all([write('/sr/api/settings/recheck', 'POST', { targets: ['download', 'mineru_local', 'mineru_api'] }), refreshConnection()])
            .then(function (results) { renderSnapshot(results[0]); notice.textContent = '状态已更新。'; }).catch(showError).finally(function () { recheck.disabled = false; });
        });
        row(details, '更新状态', '手动检测环境能力，不发送论文或启动翻译。', recheck);
        if (focusedKey) keyInput.focus();
      }
      function write(path, method, body) { return api(path, { method: method, headers: { 'Content-Type': 'application/json', 'x-sr-csrf': '1' }, body: method === 'DELETE' ? undefined : JSON.stringify(body || {}) }); }
      function showError(error) { if (!disposed) notice.textContent = '操作失败：' + (error && error.message ? error.message : '请求失败'); }
      async function refreshConnection() {
        try {
          var current = await api('/__workbench/identity');
          if (current.product !== 'codex-scientific-reading') return;
          identity = current;
          try { oauthState = await api('/api/codex-oauth'); } catch (error) { oauthState = { status: 'unavailable' }; }
        } catch (error) { /* 原生插件没有 Codex 工作台身份接口。 */ }
      }
      function load() { if (active) active.abort(); active = new AbortController(); return api('/sr/api/settings/status', { signal: active.signal }).then(renderSnapshot).catch(function (error) { if (error.name !== 'AbortError') showError(error); }); }
      if (initialSnapshot) renderSnapshot(initialSnapshot); else load();
      refreshConnection().then(function () { if (snapshot) renderSnapshot(snapshot); });
      function onFocus() { refreshConnection().then(function () { if (snapshot) renderSnapshot(snapshot); }); }
      window.addEventListener('focus', onFocus);
      shell.appendChild(el('p', 'sr-settings-footnote', '密钥保存在本机系统凭据库；使用 MinerU API 解析时才会发送论文 PDF。'));
      return { root: root, dispose: function () { disposed = true; window.removeEventListener('focus', onFocus); if (active) active.abort(); } };
    }
    // ── 设置卡片（settings.plugin.item，key=scientific-reading）─────
    var SR_NS = 'scientific-reading';
    function SettingsCard() {
      var root = el('div', 'sr-settings-card');
      root.style.cssText = 'padding:14px 4px;font-size:13px;line-height:1.6';
      root.appendChild(el('strong', '', '文献工作流设置'));
      root.appendChild(el('p', '', '模型连接、MinerU 与文献库信息请打开文献模式的“设置与状态”页。'));
      return root;
    }

    // ── 仅文献模式会话才挂 conversation.view；设置页卡片仍在插件设置里 ─────
    function isLiteraturePreset(id) {
      return id === 'scientific-reading';
    }
    function currentSessionIsLiterature(list) {
      if (!list || !list.current || !list.byId) return false;
      var row = list.byId[list.current];
      return !!(row && row.agentPreset === 'scientific-reading');
    }
    exports.inject = ['slots', 'connection', 'remote', 'sessions'];
    function apply(ctx) {
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
            return props.page === 'settings' ? renderSettingsStatus(undefined, undefined, openNativeModels) : renderLiterature(ctx.sessions, openNativeModels);
          });
        }, [props.page]);
        return React.createElement('div', { ref: mountController.ref });
      }
      ctx.effect(function () {
        var tabOff = [];
        var shown = false;
        function hideModeTabs() {
          if (!shown) return;
          shown = false;
          while (tabOff.length) {
            try { tabOff.pop()(); } catch (e) {}
          }
        }
        function showModeTabs() {
          if (shown) return;
          shown = true;
          tabOff.push(ctx.slots.inject('conversation.view', function () {
            return ctx.slots.register({
              name: 'conversation.view',
              id: 'literature',
              order: 20,
              label: function () { return '文献'; },
            }, function (props) { return React.createElement(ModeView, Object.assign({}, props, { page: 'literature' })); });
          }));
          tabOff.push(ctx.slots.inject('conversation.view', function () {
            return ctx.slots.register({
              name: 'conversation.view',
              id: 'scientific-reading-settings',
              order: 21,
              label: function () { return '设置与状态'; },
            }, function (props) { return React.createElement(ModeView, Object.assign({}, props, { page: 'settings' })); });
          }));
        }
        function syncModeTabs() {
          var list = ctx.sessions.list.getSnapshot();
          if (currentSessionIsLiterature(list)) showModeTabs();
          else hideModeTabs();
        }
        var unsub = ctx.sessions.list.subscribe(syncModeTabs);
        syncModeTabs();
        return function () {
          try { unsub(); } catch (e) {}
          hideModeTabs();
        };
      }, 'sr-mode-tabs');
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
