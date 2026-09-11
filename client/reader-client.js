(() => {
  const body = document.body;
  if (body.dataset.readerMode === 'offline' || location.protocol === 'file:') {
    document.querySelectorAll('.figure-discuss-trigger, .figure-chat-question, .figure-chat-status').forEach(node => { node.hidden = true; });
    document.querySelectorAll('a[href^="/sr/"]').forEach(node => { node.removeAttribute('href'); });
    const label = document.createElement('span'); label.className = 'sr-reader-offline-label'; label.textContent = '离线阅读'; body.append(label);
    return;
  }
  if (body.dataset.readerMode !== 'online' || !body.dataset.paperId) return;
  const article = document.querySelector('article');
  function userMessage(error) {
    const messages = {reader_source_changed:'原文已更新，请重新打开阅读页。',reader_selection_changed:'选区已变化，请重新选择。',reader_selection_invalid:'请选择正文中的片段。',reader_context_unavailable:'正文暂不可用，请重新打开阅读页。',request_forbidden:'页面已失效，请重新打开。'};
    const message = String(error.message || '');
    return messages[message] || (/[\u3400-\u9fff]/.test(message) && !/[{}]|Traceback|Error:/.test(message) ? message : '暂时无法回答，请重试。');
  }
  let selection = null, conversationId = '', busy = false, controller;
  const node = (tag, className, text) => { const value = document.createElement(tag); value.className = className; if (text) value.textContent = text; return value; };
  const launcher = node('button', 'sr-reader-launcher', '问 AI'); launcher.type = 'button'; launcher.setAttribute('aria-label', '打开阅读助手'); launcher.title = '阅读助手 · Alt + Shift + E 解释选区'; launcher.setAttribute('aria-expanded', 'false');
  const panel = node('section', 'sr-reader-chat'); panel.hidden = true; panel.setAttribute('aria-label', '阅读助手');
  const head = node('header', ''); const heading = node('h2', '', '边读边问'); head.append(heading);
  const model = node('small', '', '围绕当前论文提问'); head.append(model);
  const chatHint = node('small', '', '刷新页面后，对话不保留'); head.append(chatHint);
  const nav = node('nav', '');
  const fresh = node('button', '', '新对话'); fresh.type = 'button';
  const download = node('a', '', '导出离线阅读'); download.href = location.pathname + '?download=1'; download.download = ''; download.title = '导出论文，不包含对话';
  const close = node('button', '', '收起'); close.type = 'button'; nav.append(fresh, download, close); head.append(nav);
  const log = node('div', 'sr-reader-chat-log'); log.setAttribute('aria-label', '本页对话');
  const empty = node('p', '', '选中文字后点“问”，或按 Alt + Shift + E。'); log.append(empty);
  const quote = node('blockquote', 'sr-reader-chat-selection'); quote.hidden = true;
  const form = node('form', '');
  const input = node('textarea', ''); input.placeholder = '这句话是什么意思？这个方法为什么这样设计？'; input.setAttribute('aria-label', '向阅读助手提问'); input.maxLength = 8000;
  const actions = node('div', 'sr-reader-chat-actions');
  const clear = node('button', '', '清除选区'); clear.type = 'button';
  const stop = node('button', '', '停止'); stop.type = 'button'; stop.hidden = true;
  const send = node('button', '', '发送'); send.type = 'submit'; actions.append(clear, stop, send); form.append(input, actions);
  const status = node('span', 'sr-reader-chat-status'); status.setAttribute('role', 'status'); status.setAttribute('aria-live', 'polite');
  const noteLauncher = node('button', 'sr-reader-note-launcher', '随记'); noteLauncher.type = 'button'; noteLauncher.setAttribute('aria-label', '打开随记'); noteLauncher.setAttribute('aria-expanded', 'false');
  const dock = node('div', 'sr-reader-dock'); dock.append(launcher, noteLauncher);
  const notes = node('section', 'sr-reader-notes'); notes.hidden = true;
  const noteInput = node('textarea', ''); noteInput.setAttribute('aria-label', '随记'); noteInput.placeholder = '记下想法、问题或下一步'; noteInput.maxLength = 32767; noteInput.disabled = true;
  const noteActions = node('div', 'sr-reader-chat-actions');
  const excerpt = node('button', '', '摘录选区'); excerpt.type = 'button';
  const saveNote = node('button', '', '保存'); saveNote.type = 'button'; saveNote.disabled = true;
  const excel = node('button', '', '打开 Excel'); excel.type = 'button';
  const reload = node('button', '', '重新载入'); reload.type = 'button'; reload.hidden = true;
  const noteStatus = node('p', 'sr-reader-chat-status'); noteStatus.setAttribute('role', 'status');
  noteActions.append(excerpt, excel, saveNote); notes.append(noteInput, noteActions, noteStatus, reload);
  const tabs = node('nav', 'sr-reader-tabs');
  const chatTab = node('button', '', '问 AI'), noteTab = node('button', '', '随记'); chatTab.type = noteTab.type = 'button';
  tabs.append(chatTab, noteTab); head.append(tabs);
  panel.append(head, log, quote, form, status, notes); body.append(panel, dock);
  let mode = 'chat', noteLoaded = false, noteLoading = null, noteSaving = false, savedNote = '';
  const noteUrl = '/sr/api/reader/notes?paper_id=' + encodeURIComponent(body.dataset.paperId);
  async function request(url, value) {
    const response = await fetch(url, value === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json','x-sr-csrf':'1'}, body:JSON.stringify(value)});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error);
    return result;
  }
  function noteControls() { saveNote.disabled = !noteLoaded || noteSaving || noteInput.value === savedNote; excerpt.disabled = !noteLoaded || noteSaving || !selection; }
  function loadNotes() {
    if (noteLoading) return noteLoading;
    noteLoading = (async () => {
    noteStatus.textContent = '正在读取…';
    try {
      const result = await request(noteUrl); savedNote = result.note; noteInput.value = savedNote;
      noteLoaded = true; noteInput.disabled = false; reload.hidden = true; noteStatus.textContent = '';
    } catch (_) { noteStatus.textContent = '随记暂不可用，请重试。'; reload.hidden = false; }
    finally { noteLoading = null; noteControls(); }
    })();
    return noteLoading;
  }
  function switchMode(next) {
    mode = next; const isChat = mode === 'chat';
    heading.textContent = isChat ? '边读边问' : '随记';
    for (const item of [model, chatHint, fresh, log, form, status]) item.hidden = !isChat;
    quote.hidden = !isChat || !selection; notes.hidden = isChat;
    chatTab.setAttribute('aria-pressed', String(isChat)); noteTab.setAttribute('aria-pressed', String(!isChat));
    launcher.setAttribute('aria-expanded', String(!panel.hidden && isChat)); noteLauncher.setAttribute('aria-expanded', String(!panel.hidden && !isChat));
    if (!isChat && !noteLoaded) loadNotes();
  }
  function addNote(text) {
    if (!noteLoaded || noteSaving) return;
    noteInput.value = (noteInput.value ? noteInput.value + '\n\n' : '') + text;
    noteControls(); noteStatus.textContent = '尚未保存'; noteInput.focus();
  }
  excerpt.addEventListener('click', () => addNote('摘录：' + selection.quote + '\n原文：' + location.origin + location.pathname + '#block-' + selection.block_ids[0]));
  noteInput.addEventListener('input', () => { noteControls(); noteStatus.textContent = noteInput.value === savedNote ? '' : '尚未保存'; });
  async function persistNote() {
    if (!noteLoaded || noteSaving) return false;
    if (noteInput.value === savedNote) return true;
    noteSaving = true; noteControls(); noteStatus.textContent = '正在保存…'; const draft = noteInput.value;
    try {
      const result = await request(noteUrl, {note:draft, expected:savedNote});
      savedNote = result.note; noteStatus.textContent = noteInput.value === savedNote ? '已保存' : '已保存，仍有新修改'; reload.hidden = true; return true;
    } catch (error) {
      noteStatus.textContent = error.message === 'personal_record_conflict' ? '记录已在其他页面或 Excel 中更新。草稿已保留，请复制后重新载入。' : '保存失败，草稿已保留，请重试。';
      reload.hidden = false; return false;
    } finally { noteSaving = false; noteControls(); }
  }
  saveNote.addEventListener('click', persistNote);
  noteInput.addEventListener('keydown', event => { if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') { event.preventDefault(); persistNote(); } });
  reload.addEventListener('click', () => { if (noteInput.value !== savedNote && !confirm('重新载入会替换当前草稿，继续吗？')) return; loadNotes(); });
  excel.addEventListener('click', async () => {
    if (!await persistNote()) return;
    if (noteInput.value !== savedNote) return;
    excel.disabled = true; noteStatus.textContent = '正在打开 Excel…';
    try {
      const sync = await request('/sr/api/views', {action:'xlsx_refresh'});
      if (sync.status !== 'success') {
        noteStatus.textContent = sync.error?.code === 'xlsx_field_conflict'
          ? '随记已保存。Excel 中有不同修改，请在文献库处理后重试。'
          : '随记已保存。Excel 暂未更新，请保存并关闭表格后重试。';
        return;
      }
      const result = await request('/sr/api/excel/locate?paper_id=' + encodeURIComponent(body.dataset.paperId), {});
      noteStatus.textContent = result.selected ? '已在 Excel 中定位本文' : '已打开文献总表';
    }
    catch (_) { noteStatus.textContent = '无法打开 Excel，请在文献库重试。'; }
    finally { excel.disabled = false; }
  });
  window.addEventListener('beforeunload', event => { if (noteLoaded && noteInput.value !== savedNote) { event.preventDefault(); event.returnValue = ''; } });
  chatTab.addEventListener('click', () => switchMode('chat'));
  noteTab.addEventListener('click', () => switchMode('notes'));
  noteLauncher.addEventListener('pointerdown', capture);
  noteLauncher.addEventListener('click', () => { capture(); if (!panel.hidden && mode === 'notes') hide(); else { show(); switchMode('notes'); } });

  function show() { panel.hidden = false; switchMode('chat'); }
  function hide() { panel.hidden = true; launcher.setAttribute('aria-expanded', 'false'); noteLauncher.setAttribute('aria-expanded', 'false'); (mode === 'chat' ? launcher : noteLauncher).focus(); }
  function paintSelection() { quote.textContent = selection?.quote || ''; quote.hidden = mode !== 'chat' || !selection; clear.disabled = !selection; noteControls(); }
  function capture() {
    const current = window.getSelection();
    if (!current?.rangeCount || !current.toString().trim()) return;
    const range = current.getRangeAt(0);
    if (!article.contains(range.startContainer) || !article.contains(range.endContainer)) return;
    const blocks = [...article.querySelectorAll('.reading-block[data-block]')].filter(block => range.intersectsNode(block));
    if (!blocks.length) return;
    selection = {quote: current.toString().trim(), block_ids: blocks.map(block => block.dataset.block)};
    paintSelection();
  }
  document.addEventListener('mouseup', capture);
  document.addEventListener('selectionchange', capture);
  document.addEventListener('touchend', () => setTimeout(capture, 0), {passive:true});
  launcher.addEventListener('pointerdown', capture);
  launcher.addEventListener('click', () => { capture(); if (!panel.hidden && mode === 'chat') hide(); else show(); });
  close.addEventListener('click', hide);
  clear.addEventListener('click', () => { selection = null; window.getSelection()?.removeAllRanges(); paintSelection(); });
  stop.addEventListener('click', () => controller?.abort());
  fresh.addEventListener('click', () => { if (busy) return; conversationId = ''; log.replaceChildren(empty); status.textContent = '已开始新对话。'; });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !panel.hidden) { hide(); return; }
    if (event.altKey && event.shiftKey && event.code === 'KeyE') {
      event.preventDefault(); capture(); show();
      if (selection && !busy) { input.value = '请解释选中的片段，并说明它在本文中的含义。'; form.requestSubmit(); }
      else input.focus();
    }
  });
  input.addEventListener('keydown', event => { if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') { event.preventDefault(); form.requestSubmit(); } });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy) return;
    const question = input.value.trim() || (selection ? '请解释选中的片段，并说明它在本文中的含义。' : '');
    if (!question) { input.focus(); return; }
    busy = true; send.disabled = true; fresh.disabled = true; stop.hidden = false; input.value = '';
    empty.remove(); log.append(node('p', 'sr-reader-chat-message', question)); log.lastChild.dataset.role = 'user';
    const answer = node('p', 'sr-reader-chat-message'); answer.dataset.role = 'assistant'; log.append(answer);
    const sources = node('div', 'sr-reader-chat-sources'); log.append(sources);
    status.textContent = '正在读取原文…'; controller = new AbortController();
    let finished = false;
    try {
      const response = await fetch('/sr/api/reader/chat', {method:'POST', signal:controller.signal,
        headers:{'Content-Type':'application/json','x-sr-csrf':'1'}, body:JSON.stringify({paper_id:body.dataset.paperId,
          source_pdf_sha256:body.dataset.sourcePdfSha256, conversation_id:conversationId || undefined, question, selection})});
      if (!response.ok) throw new Error((await response.json()).error || '请求失败');
      const reader = response.body.getReader(), decoder = new TextDecoder(); let pending = '';
      function consume(line) {
        if (!line.trim()) return;
        const value = JSON.parse(line);
        if (value.type === 'context') {
          conversationId = value.conversation_id; model.textContent = value.model;
          status.textContent = '正在回答…';
          value.passages.forEach(row => { if (row.anchor) { const link = node('a', '', '原文 ' + (sources.childElementCount + 1)); link.href = '#' + encodeURIComponent(row.anchor); sources.append(link); } });
        } else if (value.type === 'text') { answer.append(document.createTextNode(value.text)); log.scrollTop = log.scrollHeight; }
        else if (value.type === 'error') throw new Error(value.error);
        else if (value.type === 'done') finished = true;
      }
      while (true) {
        const {done, value} = await reader.read(); pending += done ? decoder.decode() : decoder.decode(value, {stream:true});
        const lines = pending.split('\n'); pending = lines.pop(); lines.forEach(consume);
        if (done) { if (pending) consume(pending); break; }
      }
      if (!finished) throw new Error('连接中断，回答未完成');
      status.textContent = '可继续追问';
      const keep = node('button', 'sr-reader-keep-note', '存入随记'); keep.type = 'button';
      keep.addEventListener('click', async () => { switchMode('notes'); if (!noteLoaded) await loadNotes(); addNote('AI 解读（待核对）：\n' + answer.textContent); });
      sources.append(keep);
    } catch (error) { status.textContent = error.name === 'AbortError' ? '已停止生成。' : userMessage(error); if (!answer.textContent) answer.remove(); }
    finally { busy = false; send.disabled = false; fresh.disabled = false; stop.hidden = true; }
  });
  paintSelection();
})();
