from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag


READER_BUILD_VERSION = "reader-html-v2.4.4-english-first"
ALLOWED_HIGHLIGHT_KINDS = frozenset({"result", "method"})
ALLOWED_HIGHLIGHT_SOURCES = ALLOWED_HIGHLIGHT_KINDS


def normalize_highlight_kind(value: str) -> str:
    if value not in ALLOWED_HIGHLIGHT_KINDS:
        raise ValueError("highlight_kind_invalid")
    return value


CSS = r"""
:root {
  color-scheme: light;
  --canvas: #ece9e1;
  --paper: #fffef9;
  --paper-muted: #f7f5ee;
  --ink: #252822;
  --muted: #6e726a;
  --line: #d9d6ca;
  --accent: #405f54;
  --accent-soft: #e4ece7;
  --quick: #a86624;
  --quick-soft: #fff4d8;
  --review: #4b6f95;
  --review-soft: #e8f0f8;
  --quick-dot: #f3b51b;
  --review-dot: #2f80ed;
  --sidebar: 260px;
  --text-width: 800px;
  --asset-width: 1020px;
  --shadow: 0 14px 38px rgba(49, 47, 40, .055);
}

* { box-sizing: border-box; }
html { scroll-behavior: smooth; scroll-padding-top: 64px; }
body {
  margin: 0;
  background: #f3f1eb;
  color: var(--ink);
  font-family: "Source Han Serif SC", "Noto Serif CJK SC", "Noto Serif SC", "Songti SC", STSong, serif;
}
button, summary, a { -webkit-tap-highlight-color: transparent; }
a { color: inherit; }

.reading-progress {
  position: fixed;
  inset: 0 auto auto 0;
  z-index: 20;
  width: 0;
  height: 3px;
  background: var(--accent);
  transition: width .12s linear;
}

.reader-shell {
  display: grid;
  grid-template-columns: var(--sidebar) minmax(0, var(--asset-width));
  gap: 24px;
  width: min(1320px, calc(100% - 40px));
  margin: 0 auto;
  padding: 20px 0 72px;
  align-items: start;
  transition: width .2s ease;
}

.reader-sidebar {
  position: sticky;
  top: 24px;
  height: calc(100vh - 48px);
  display: flex;
  flex-direction: column;
  min-width: 0;
  transition: opacity .16s ease, transform .16s ease;
}

body.sidebar-collapsed .reader-shell {
  grid-template-columns: minmax(0, var(--asset-width));
  width: min(var(--asset-width), calc(100% - 40px));
}
body.sidebar-collapsed .reader-sidebar { display: none; }

.reader-mark {
  padding: 10px 12px 17px;
  border-bottom: 1px solid rgba(64, 95, 84, .22);
  color: var(--accent);
  letter-spacing: .08em;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
}
.reader-mark strong {
  display: block;
  margin-top: 5px;
  color: var(--ink);
  font-family: "Source Han Sans SC", "Noto Sans CJK SC", "Microsoft YaHei", SimHei, sans-serif;
  font-size: 19px;
  letter-spacing: 0;
  text-transform: none;
}

.toc {
  flex: 1;
  min-height: 0;
  margin: 16px 0;
  padding: 0 8px 0 0;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: #b9bdb5 transparent;
}
.toc::before {
  content: "目录";
  display: block;
  margin: 0 0 8px 12px;
  color: var(--muted);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .18em;
}
.toc ul { list-style: none; margin: 0; padding: 0; }
.toc li { margin: 1px 0; }
.toc a {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 7px 10px 7px 13px;
  border-radius: 6px;
  color: #666b63;
  text-decoration: none;
  font-size: 13px;
  line-height: 1.45;
  transition: background .16s ease, color .16s ease;
}
.toc-label { flex: 1; min-width: 0; }
.toc-marks {
  display: inline-flex;
  flex: 0 0 auto;
  gap: 4px;
  margin-top: .43em;
}
.toc-mark {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  box-shadow: 0 0 0 2px rgba(255, 254, 249, .72);
}
.toc-mark.result { background: var(--quick-dot); }
.toc-mark.method { background: var(--review-dot); }
.toc-mark.figure,
.toc-mark.table {
  width: auto;
  min-width: 14px;
  height: 14px;
  padding: 0 3px;
  border-radius: 4px;
  background: #e7e3d8;
  color: #59625c;
  font-size: 8px;
  font-weight: 800;
  line-height: 14px;
  text-align: center;
}
.toc a:hover { background: rgba(255, 255, 255, .52); color: var(--ink); }
.toc a.active { background: var(--accent-soft); color: #27483d; font-weight: 650; }
.toc a.active::before {
  content: "";
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 3px;
  border-radius: 4px;
  background: var(--accent);
}
.toc .toc-h3 a { padding-left: 25px; color: #797d75; font-size: 12px; }

.sidebar-guide {
  flex: 0 0 auto;
  max-height: 43vh;
  margin: 13px 0 4px;
  padding: 0 8px 10px 0;
  overflow-y: auto;
  border-bottom: 1px solid rgba(64, 95, 84, .18);
}
.guide-heading {
  margin: 0 0 6px 12px;
  color: var(--muted);
  font: 700 11px/1.4 "Source Han Sans SC", "Microsoft YaHei", sans-serif;
  letter-spacing: .14em;
}
.sidebar-guide-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 4px 8px;
  padding: 7px 10px 8px 12px;
  border-top: 1px solid rgba(64, 95, 84, .1);
  font-family: "Source Han Sans SC", "Microsoft YaHei", sans-serif;
}
.sidebar-guide-item:first-child { border-top: 0; }
.sidebar-guide-item details { min-width: 0; }
.sidebar-guide-item summary { cursor: pointer; list-style: none; }
.sidebar-guide-item summary::-webkit-details-marker { display: none; }
.sidebar-guide-item summary strong { display: block; color: #315348; font-size: 12px; }
.sidebar-guide-preview {
  display: block;
  margin-top: 2px;
  overflow: hidden;
  color: #737970;
  font-size: 11px;
  line-height: 1.45;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sidebar-guide-item details[open] .sidebar-guide-preview { white-space: normal; }
.sidebar-guide-content { grid-column: 1 / -1; color: #59615b; font-size: 11px; line-height: 1.5; }
.sidebar-guide-content .guide-list { margin: 6px 0 0; padding-left: 1rem; }
.sidebar-guide-content .guide-entry { margin: 5px 0; }
.guide-empty { margin: 5px 0 0; color: #8a8d86; }
.sidebar-guide-jump {
  align-self: start;
  margin-top: 1px;
  color: #2f6656;
  font-size: 10px;
  font-weight: 700;
  text-decoration: none;
  white-space: nowrap;
}
.sidebar-guide-jump:hover, .sidebar-guide-jump:focus-visible { text-decoration: underline; }

.reader-main { width: min(var(--asset-width), 100%); min-width: 0; max-width: 100%; }
.reader-toolbar {
  position: sticky;
  top: 0;
  z-index: 15;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 42px;
  margin: 0;
  padding: 5px 10px;
  border-bottom: 1px solid rgba(64, 95, 84, .12);
  background: rgba(243, 241, 235, .94);
  box-shadow: 0 6px 16px rgba(49, 47, 40, .025);
  backdrop-filter: blur(10px);
  color: #5e635b;
  font: 12px/1.4 "Source Han Sans SC", "Microsoft YaHei", sans-serif;
}
.toolbar-primary, .toolbar-controls, .control-group { display: flex; align-items: center; }
.toolbar-primary { gap: 6px; }
.toolbar-controls { gap: 12px; }
.sidebar-toggle {
  min-height: 28px;
  padding: 4px 8px;
  border: 0;
  background: transparent;
  color: #3f574e;
  font: inherit;
  cursor: pointer;
}
.resume-reading, .control-group button {
  min-height: 28px;
  padding: 4px 8px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: #495148;
  font: inherit;
  cursor: pointer;
}
.control-group {
  gap: 2px;
  padding: 2px;
  border: 1px solid rgba(64, 95, 84, .15);
  border-radius: 7px;
  background: rgba(255, 254, 249, .62);
}
.reader-toolbar button:hover { color: #244a3b; background: rgba(64, 95, 84, .07); }
.control-group button[aria-pressed="true"] { background: #315849; color: #fff; }
.reader-toolbar button:disabled { cursor: default; opacity: .48; }
.reader-toolbar button:focus-visible, .sidebar-guide-item summary:focus-visible {
  outline: 2px solid rgba(47, 128, 237, .55);
  outline-offset: 2px;
}

.paper-card {
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  border: 1px solid rgba(63, 60, 50, .08);
  border-radius: 4px;
  background: #fff;
  box-shadow: var(--shadow);
}
.paper-hero {
  width: min(var(--text-width), calc(100% - 48px));
  margin: 0 auto;
  padding: 62px 0 20px;
  background: #fff;
  overflow-wrap: anywhere;
}
.paper-hero h1 {
  margin: 0 0 18px;
  color: #20241f;
  font-family: "Source Han Sans SC", "Noto Sans CJK SC", "Microsoft YaHei", SimHei, sans-serif;
  font-size: clamp(32px, 4vw, 44px);
  font-weight: 800;
  line-height: 1.24;
  letter-spacing: -.018em;
}
.original-title {
  margin: -6px 0 18px;
  color: #666c64;
  font-family: "Times New Roman", Georgia, serif;
  font-size: 15px;
  font-style: italic;
  line-height: 1.55;
}
.paper-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  color: var(--muted);
  font-family: "Source Han Sans SC", "Microsoft YaHei", sans-serif;
  font-size: 12px;
  line-height: 1.55;
}
.paper-meta p { margin: 0; }

article {
  padding: 0 0 76px;
  color: #2d302b;
  font-family: "Source Han Serif SC", "Noto Serif CJK SC", "Noto Serif SC", "Songti SC", STSong, serif;
  font-size: 17px;
  line-height: 1.82;
  overflow-wrap: anywhere;
}
article > :not(.paper-asset) { width: min(var(--text-width), calc(100% - 48px)); margin-right: auto; margin-left: auto; }
article > .paper-asset { width: min(var(--asset-width), calc(100% - 20px)); margin-right: auto; margin-left: auto; }
.frontmatter-source { display: none; }
article h2, article h3 {
  scroll-margin-top: 64px;
  color: #24362f;
  font-family: "Source Han Sans SC", "Noto Sans CJK SC", "Microsoft YaHei", SimHei, sans-serif;
}
article h2 {
  margin-top: 3.1rem;
  margin-bottom: 1.2rem;
  padding-bottom: .58rem;
  border-bottom: 1px solid #d9ddd7;
  font-size: 1.58rem;
  line-height: 1.35;
}
article h2#abstract { margin-top: 1.55rem; }
article h3 { margin-top: 2.2rem; margin-bottom: 1rem; font-size: 1.2rem; line-height: 1.4; }
article p { margin: .75rem 0 1rem; }
article ol, article ul { margin: .8rem 0 1.15rem; padding-left: 1.45rem; }
article li { margin: .35rem 0; padding-left: .25rem; }
article img {
  display: block;
  max-width: 100%;
  height: auto;
  margin: 1.9rem auto .8rem;
  border: 1px solid #e2dfd5;
  border-radius: 7px;
  background: #fff;
}
article table {
  display: block;
  max-width: 100%;
  margin: 1.5rem 0;
  overflow-x: auto;
  border-collapse: collapse;
  font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
  font-size: 13px;
  line-height: 1.55;
}
article th, article td { padding: .55rem .65rem; border: 1px solid #d6d4cb; text-align: left; }
article th { background: var(--paper-muted); color: #3c4c45; }
.paper-asset { position: relative; }
.paper-asset > .reading-block {
  width: min(var(--text-width), calc(100% - 28px));
  margin-right: auto;
  margin-left: auto;
}
.asset-caption, figcaption {
  margin: .72rem 0 1.2rem;
  color: #5f655e;
  font-family: "Source Han Sans SC", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
  font-size: 13px;
  line-height: 1.62;
}
.asset-dialog-trigger { touch-action: manipulation; }
.asset-image-trigger {
  display: block;
  width: 100%;
  padding: 0;
  border: 0;
  background: transparent;
  color: inherit;
  cursor: zoom-in;
}
.asset-image-trigger:focus-visible {
  outline: 3px solid rgba(47, 128, 237, .55);
  outline-offset: 4px;
  border-radius: 8px;
}
.asset-table-trigger {
  display: inline-flex;
  align-items: center;
  margin: .35rem 0 -.8rem;
  padding: 5px 9px;
  border: 1px solid #cbc9bf;
  border-radius: 6px;
  background: #faf9f4;
  color: #4d5b54;
  font: 600 11px/1.4 "Segoe UI", "Microsoft YaHei", sans-serif;
  cursor: zoom-in;
}
.asset-table-trigger:hover { border-color: #8da097; background: #fff; }

#asset-dialog {
  width: min(94vw, 1380px);
  max-width: none;
  max-height: 92vh;
  padding: 0;
  border: 0;
  border-radius: 12px;
  background: #fdfcf7;
  color: var(--ink);
  box-shadow: 0 28px 90px rgba(20, 24, 21, .32);
}
#asset-dialog::backdrop { background: rgba(24, 29, 26, .66); }
.asset-dialog-panel { display: flex; flex-direction: column; max-height: 92vh; }
.asset-dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--line);
  font: 700 13px/1.4 "Segoe UI", "Microsoft YaHei", sans-serif;
}
.asset-dialog-close {
  padding: 5px 10px;
  border: 1px solid #cbc9bf;
  border-radius: 6px;
  background: #fffef9;
  color: #495148;
  font: inherit;
  cursor: pointer;
}
.asset-dialog-content { padding: 20px; overflow: auto; }
.asset-dialog-content img { display: block; max-width: none; height: auto; margin: 0 auto; }
.asset-dialog-content table {
  width: max-content;
  min-width: 100%;
  border-collapse: collapse;
  font: 13px/1.55 "Segoe UI", "Microsoft YaHei", sans-serif;
}
.asset-dialog-content th,
.asset-dialog-content td { padding: .55rem .65rem; border: 1px solid #d6d4cb; text-align: left; }
.asset-dialog-content th { background: var(--paper-muted); color: #3c4c45; }

.citation-trigger {
  display: inline;
  margin: 0 .08em;
  padding: 0 .24em;
  border: 0;
  border-radius: 4px;
  background: #edf2ef;
  color: #315f50;
  font: inherit;
  line-height: inherit;
  cursor: pointer;
}
.citation-trigger:hover, .citation-trigger:focus-visible { background: #dce9e2; }
#citation-dialog {
  width: min(620px, calc(100% - 28px));
  max-height: min(78vh, 760px);
  padding: 0;
  border: 1px solid #c9cdc7;
  border-radius: 10px;
  background: var(--paper);
  color: var(--ink);
  box-shadow: 0 24px 70px rgba(31, 38, 34, .28);
}
#citation-dialog::backdrop { background: rgba(24, 29, 26, .48); }
.citation-dialog-panel { display: flex; flex-direction: column; max-height: inherit; }
.citation-dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border-bottom: 1px solid var(--line);
  font-family: "Source Han Sans SC", "Microsoft YaHei", sans-serif;
  font-weight: 700;
}
.citation-dialog-content { padding: 14px; overflow: auto; }
.citation-card { padding: 12px 0; border-top: 1px solid #e5e2d9; }
.citation-card:first-child { padding-top: 0; border-top: 0; }
.citation-card-label { color: var(--accent); font: 700 12px/1.4 "Source Han Sans SC", "Microsoft YaHei", sans-serif; }
.citation-card-reference { margin: .45rem 0; font-size: 15px; line-height: 1.65; }
.citation-card-meta { color: var(--muted); font-size: 12px; }
.citation-card-action { margin-top: .65rem; }
.reading-queue-open { white-space: nowrap; }
#reading-queue-dialog {
  width: min(700px, calc(100% - 28px));
  max-height: min(82vh, 820px);
  padding: 0;
  border: 1px solid #c9cdc7;
  border-radius: 10px;
  background: var(--paper);
  color: var(--ink);
  box-shadow: 0 24px 70px rgba(31, 38, 34, .28);
}
#reading-queue-dialog::backdrop { background: rgba(24, 29, 26, .48); }
.reading-queue-panel { display: flex; flex-direction: column; max-height: inherit; }
.reading-queue-items { min-height: 110px; padding: 14px; overflow: auto; }
.reading-queue-empty { margin: 30px 0; color: var(--muted); text-align: center; }
.reading-queue-item { padding: 12px 0; border-top: 1px solid #e5e2d9; }
.reading-queue-item:first-child { padding-top: 0; border-top: 0; }
.reading-queue-item-reference { margin: 0 0 .45rem; font-size: 14px; line-height: 1.58; }
.reading-queue-item-meta { color: var(--muted); font-size: 12px; }
.reading-queue-remove { margin-top: .55rem; }
.reading-queue-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 11px 14px;
  border-top: 1px solid var(--line);
}
.reading-queue-actions button:last-child { margin-left: auto; }

.reading-block {
  position: relative;
  margin: 0;
  padding-top: 1px;
  padding-bottom: 1px;
  transition: opacity .18s ease, background .18s ease;
}
.reading-block.is-highlighted { margin-top: .5rem; margin-bottom: .5rem; }
.reading-block { scroll-margin-top: 88px; }
.reading-block.is-highlighted[data-highlight-kind="result"] .highlight-ink {
  background: linear-gradient(transparent 10%, rgba(255, 224, 105, .32) 10%, rgba(255, 224, 105, .32) 92%, transparent 92%);
}
.reading-block.is-highlighted[data-highlight-kind="method"] .highlight-ink {
  background: linear-gradient(transparent 10%, rgba(103, 174, 247, .22) 10%, rgba(103, 174, 247, .22) 92%, transparent 92%);
}
.highlight-ink {
  -webkit-box-decoration-break: clone;
  box-decoration-break: clone;
  padding: .04em .08em;
  margin: 0 -.08em;
}
math[display="inline"] { font-size: 1.02em; }
math[display="block"] {
  display: block;
  max-width: 100%;
  margin: 1rem auto;
  overflow-x: auto;
  overflow-y: hidden;
}

.reading-group {
  margin: .75rem 0 1.2rem;
  padding: .25rem 0 .15rem;
  border-top: 1px solid #ece9df;
  border-bottom: 1px solid #ece9df;
}
.reading-group > .reading-block {
  margin: 0;
  padding-top: 0;
  padding-bottom: 0;
}
.reading-group > .reading-block:not(.is-highlighted) {
  background: transparent;
}
.reading-group > .reading-block > ol,
.reading-group > .reading-block > ul {
  margin: .15rem 0;
}
.reading-group > .reading-block > .source-text { display: none; }
.reading-group > .reading-block.is-highlighted {
  margin: .35rem 0;
  padding-top: .3rem;
  padding-bottom: .3rem;
}
.highlight-label {
  position: absolute;
  top: 1.05rem;
  left: -17px;
  width: 9px;
  height: 9px;
  overflow: visible;
  border-radius: 50%;
  background: var(--quick-dot);
  color: transparent;
  cursor: help;
  font: 0/0 a;
}
[data-highlight-kind="method"] .highlight-label { background: var(--review-dot); }
.highlight-label::after {
  content: attr(data-reason);
  position: absolute;
  left: 15px;
  top: -8px;
  z-index: 4;
  display: none;
  width: max-content;
  max-width: 260px;
  padding: 6px 8px;
  border: 1px solid #d4d2c8;
  border-radius: 5px;
  background: #fffef9;
  color: #4f574f;
  box-shadow: 0 6px 18px rgba(40, 43, 39, .12);
  font: 11px/1.45 "Source Han Sans SC", "Microsoft YaHei", sans-serif;
}
.highlight-label:hover::after, .highlight-label:focus-visible::after { display: block; }

.source-text {
  margin: .2rem 0 .75rem;
  color: #71756d;
  font-family: Georgia, "Times New Roman", serif;
  font-size: 15px;
  line-height: 1.72;
}
.source-text summary {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 0;
  margin-left: auto;
  color: #778078;
  font-family: "Source Han Sans SC", "Microsoft YaHei", sans-serif;
  font-size: 10px;
  cursor: pointer;
  list-style: none;
}
.source-text summary::-webkit-details-marker { display: none; }
.source-text summary::before { content: "EN"; color: var(--accent); font-weight: 750; letter-spacing: .08em; }
.source-text[open] summary::before { content: "EN"; }
.source-text[open] p {
  margin: .45rem 0 .7rem;
  padding: 10px 13px;
  border-left: 2px solid #c8d1cc;
  background: #f5f6f2;
  color: #62675f;
}
.source-text-group {
  margin: .65rem 18px .7rem;
  padding-top: .45rem;
  border-top: 1px dashed #d8d6cd;
}
.source-text-group[open] .source-list {
  margin: .5rem 0 .75rem;
  padding: 11px 14px 11px 2.25rem;
  border-left: 2px solid #c8d1cc;
  background: #f5f6f2;
  color: #62675f;
}
.source-text-group .source-list li { margin: .25rem 0; padding-left: .2rem; }

.source-primary { cursor: pointer; }
.reading-block:has(> .translation-panel) { outline: none; }
.reading-block:has(> .translation-panel):focus-visible {
  border-radius: 3px;
  box-shadow: 0 0 0 2px rgba(64, 95, 84, .2);
}
.translation-panel {
  margin: .65rem 0 .2rem;
  padding: .7rem .85rem;
  border-left: 2px solid rgba(64, 95, 84, .32);
  background: rgba(228, 236, 231, .38);
  color: #4f5751;
  font-family: "Source Han Serif SC", "Noto Serif CJK SC", "Songti SC", STSong, serif;
  font-size: .94em;
  line-height: 1.78;
}
.translation-panel[hidden] { display: none !important; }
.translation-panel > :first-child { margin-top: 0; }
.translation-panel > :last-child { margin-bottom: 0; }
.low-value-region {
  width: var(--text-width);
  max-width: calc(100% - 48px);
  margin: 1.25rem auto;
  border: 1px solid #dedbd1;
  border-radius: 7px;
  background: #faf9f4;
}
.low-value-region > summary {
  cursor: pointer;
  padding: .7rem .85rem;
  color: #72766f;
  font: 650 13px/1.45 "Source Han Sans SC", "Microsoft YaHei", sans-serif;
  list-style-position: inside;
}
.low-value-region[open] > summary { border-bottom: 1px solid #e4e1d8; }
.low-value-content { padding: .25rem 0 .8rem; }
.low-value-content > * { max-width: calc(100% - 32px); margin-right: auto; margin-left: auto; }

body.highlights-off .reading-block.is-highlighted .highlight-ink { background: transparent; }
body.highlights-off .highlight-label { display: none; }
body.highlights-off .toc-mark.result,
body.highlights-off .toc-mark.method { display: none; }
article.focus-only > * { display: none; }
article.focus-only > .reading-block.is-highlighted,
article.focus-only > .reading-group.has-highlight,
article.focus-only > .paper-asset.focus-near-highlight,
article.focus-only > .focus-heading { display: block; }
article.focus-only .reading-block.is-highlighted { break-inside: avoid; }

.mobile-nav { display: none; }
.review-warning { border-left: 4px solid #b7772c; padding-left: .8rem; }

@media (max-width: 1000px) {
  .reader-shell { display: block; width: min(920px, calc(100% - 32px)); padding-top: 18px; }
  .reader-sidebar { display: none; }
  .sidebar-toggle { display: none; }
  .mobile-nav {
    display: block;
    margin: 0 0 12px;
    border: 1px solid rgba(64, 95, 84, .18);
    border-radius: 9px;
    background: rgba(255, 254, 249, .75);
  }
  .mobile-nav > summary { padding: 11px 14px; color: #3f574e; cursor: pointer; font-size: 13px; font-weight: 650; }
  .mobile-nav-panel { padding: 0 10px 12px; }
  .mobile-nav .sidebar-guide { max-height: none; }
  .mobile-nav .toc { max-height: 42vh; margin: 0; padding: 4px 10px 12px; overflow-y: auto; }
  .mobile-nav .toc::before { display: none; }
  .reader-toolbar { flex-wrap: wrap; }
}

@media (max-width: 680px) {
  body { overflow-x: hidden; }
  .reader-shell { width: 100%; padding: 0 0 28px; }
  .reader-main { width: 100vw; max-width: 100vw; overflow: clip; }
  .mobile-nav { margin: 10px 10px 8px; }
  .reader-toolbar { justify-content: space-between; gap: 5px; padding: 4px 8px; margin: 0; }
  .toolbar-controls { gap: 5px; }
  .control-group button { min-width: 39px; padding-right: 6px; padding-left: 6px; }
  .paper-card { border-right: 0; border-left: 0; border-radius: 0; box-shadow: none; }
  .paper-hero { width: calc(100% - 40px); padding: 38px 0 16px; }
  .paper-hero h1 { font-size: 30px; }
  .paper-meta { display: block; }
  article { padding: 0 0 52px; font-size: 16px; line-height: 1.78; }
  article > :not(.paper-asset) { width: calc(100% - 40px); }
  article > .paper-asset { width: calc(100% - 20px); }
  article h2 { font-size: 1.45rem; }
  .highlight-label { left: auto; right: -14px; }
  .highlight-label::after { right: 16px; left: auto; }
}

@media print {
  body { background: #fff; }
  .reading-progress, .reader-sidebar, .reader-toolbar, .mobile-nav { display: none !important; }
  .reader-shell { display: block; width: auto; padding: 0; }
  .paper-card { border: 0; box-shadow: none; }
  .paper-hero, article { padding-right: 0; padding-left: 0; }
  .source-text:not([open]) { display: none; }
  .asset-image-trigger { display: contents; }
  .asset-table-trigger, #asset-dialog { display: none !important; }
}
"""


SCRIPT = r"""
(() => {
  const body = document.body;
  const article = document.querySelector('article');
  const sidebarButton = document.querySelector('#toggle-sidebar');
  const languageButtons = [...document.querySelectorAll('button[data-language]')];
  const readingButtons = [...document.querySelectorAll('button[data-reading]')];
  const resumeButton = document.querySelector('#resume-reading');
  const progress = document.querySelector('.reading-progress');
  const tocLinks = [...document.querySelectorAll('.toc a')];
  const translationPanels = [...document.querySelectorAll('.translation-panel')];
  const translatableBlocks = [...document.querySelectorAll('.reading-block:has(> .translation-panel)')];
  const lowValueRegions = [...document.querySelectorAll('details.low-value-region')];
  const paperId = body.dataset.paperId || '';
  const readerRevision = body.dataset.readerRevision || '';
  const storageKey = `sr-reader:${paperId}`;
  const translationStorageKey = `sr-reader-translations:${paperId}:${readerRevision}`;
  const regionStorageKey = `sr-reader-regions:${paperId}:${readerRevision}`;
  let savedAtLoad = null;
  let storageAvailable = Boolean(paperId && readerRevision);
  let lastSavedAt = 0;
  let scrollFramePending = false;
  let expandedTranslations = new Set();
  let savedRegions = new Set();

  try {
    const raw = storageAvailable ? localStorage.getItem(storageKey) : null;
    const saved = raw ? JSON.parse(raw) : null;
    if (saved && saved.paperId === paperId && typeof saved.readerRevision === 'string') {
      savedAtLoad = saved;
    }
  } catch (_error) {
    storageAvailable = false;
  }
  try {
    const rawTranslations = storageAvailable
      ? localStorage.getItem(translationStorageKey)
      : null;
    const savedTranslations = rawTranslations ? JSON.parse(rawTranslations) : [];
    if (Array.isArray(savedTranslations)) {
      expandedTranslations = new Set(savedTranslations.filter((value) => typeof value === 'string'));
    }
  } catch (_error) {
    expandedTranslations = new Set();
  }
  try {
    const rawRegions = storageAvailable ? localStorage.getItem(regionStorageKey) : null;
    const parsedRegions = rawRegions ? JSON.parse(rawRegions) : [];
    if (Array.isArray(parsedRegions)) {
      savedRegions = new Set(parsedRegions.filter((value) => typeof value === 'string'));
    }
  } catch (_error) {
    savedRegions = new Set();
  }
  resumeButton.disabled = !savedAtLoad;
  resumeButton.hidden = !savedAtLoad;

  sidebarButton.addEventListener('click', () => {
    const collapsed = body.classList.toggle('sidebar-collapsed');
    sidebarButton.setAttribute('aria-expanded', String(!collapsed));
  });

  const persistTranslations = () => {
    if (!storageAvailable) return;
    try {
      localStorage.setItem(translationStorageKey, JSON.stringify([...expandedTranslations].sort()));
    } catch (_error) {
      storageAvailable = false;
    }
  };

  const setBlockTranslation = (block, expanded, persist = true) => {
    const panel = block.querySelector(':scope > .translation-panel');
    if (!panel) return;
    panel.hidden = !expanded;
    block.classList.toggle('translation-expanded', expanded);
    block.setAttribute('aria-expanded', String(expanded));
    const blockId = block.dataset.block;
    if (blockId) {
      if (expanded) expandedTranslations.add(blockId);
      else expandedTranslations.delete(blockId);
    }
    if (persist) persistTranslations();
  };

  const persistRegions = () => {
    if (!storageAvailable) return;
    try {
      localStorage.setItem(regionStorageKey, JSON.stringify([...savedRegions].sort()));
    } catch (_error) {
      storageAvailable = false;
    }
  };
  lowValueRegions.forEach((region) => {
    region.open = savedRegions.has(region.id);
    region.addEventListener('toggle', () => {
      if (region.open) savedRegions.add(region.id);
      else savedRegions.delete(region.id);
      persistRegions();
    });
  });
  const revealLowValueTarget = (target) => {
    const region = target ? target.closest('details.low-value-region') : null;
    if (region) region.open = true;
  };
  tocLinks.forEach((link) => {
    link.addEventListener('click', () => {
      const target = document.getElementById(link.hash.slice(1));
      revealLowValueTarget(target);
    });
  });

  const setLanguage = (language) => {
    const bilingual = language === 'bilingual';
    body.dataset.language = language;
    translatableBlocks.forEach((block) => {
      setBlockTranslation(
        block,
        bilingual || expandedTranslations.has(block.dataset.block),
        false,
      );
    });
    languageButtons.forEach((button) => {
      button.setAttribute('aria-pressed', String(button.dataset.language === language));
    });
  };

  const setReadingMode = (mode) => {
    body.dataset.reading = mode;
    body.classList.toggle('highlights-off', mode === 'clean');
    article.classList.toggle('focus-only', mode === 'focus');
    readingButtons.forEach((button) => {
      button.setAttribute('aria-pressed', String(button.dataset.reading === mode));
    });
  };

  languageButtons.forEach((button) => {
    button.addEventListener('click', () => setLanguage(button.dataset.language));
  });
  translatableBlocks.forEach((block) => {
    block.addEventListener('click', (event) => {
      if (body.dataset.language === 'bilingual') return;
      if (event.target.closest('a, button, summary, details, dialog, .paper-asset')) return;
      const selection = window.getSelection ? window.getSelection().toString().trim() : '';
      if (selection) return;
      setBlockTranslation(block, block.getAttribute('aria-expanded') !== 'true');
    });
    block.addEventListener('keydown', (event) => {
      if (body.dataset.language === 'bilingual') return;
      if (event.key !== 'Enter' && event.key !== ' ') return;
      event.preventDefault();
      setBlockTranslation(block, block.getAttribute('aria-expanded') !== 'true');
    });
  });
  readingButtons.forEach((button) => {
    button.addEventListener('click', () => setReadingMode(button.dataset.reading));
  });
  setLanguage(body.dataset.language || 'en');
  setReadingMode(body.dataset.reading || 'full');

  const updateProgress = () => {
    const max = document.documentElement.scrollHeight - innerHeight;
    progress.style.width = `${max > 0 ? (scrollY / max) * 100 : 0}%`;
  };

  const findCurrentAnchor = () => {
    const y = Math.min(Math.max(96, innerHeight * .18), innerHeight - 1);
    for (const element of document.elementsFromPoint(innerWidth / 2, y)) {
      const anchor = element.closest('.reading-block[data-block], h2[id], h3[id]');
      if (anchor && article.contains(anchor)) return anchor;
      const asset = element.closest('.paper-asset[data-progress-anchor]');
      if (asset && article.contains(asset)) {
        const target = document.getElementById(asset.dataset.progressAnchor);
        if (target) return target;
      }
    }
    return null;
  };

  const persistProgress = () => {
    if (!storageAvailable) return;
    const now = Date.now();
    if (now - lastSavedAt < 250) return;
    lastSavedAt = now;
    const anchor = findCurrentAnchor();
    const max = document.documentElement.scrollHeight - innerHeight;
    const state = {
      paperId,
      readerRevision,
      blockId: anchor ? (anchor.dataset.block || anchor.id || null) : null,
      scrollRatio: max > 0 ? Math.min(1, Math.max(0, scrollY / max)) : 0,
      updatedAt: new Date().toISOString(),
    };
    try {
      localStorage.setItem(storageKey, JSON.stringify(state));
    } catch (_error) {
      storageAvailable = false;
      resumeButton.disabled = true;
      resumeButton.hidden = true;
    }
  };

  const scheduleScrollUpdate = () => {
    if (scrollFramePending) return;
    scrollFramePending = true;
    requestAnimationFrame(() => {
      scrollFramePending = false;
      updateProgress();
      persistProgress();
    });
  };

  const restoreSavedPosition = (saved, smooth) => {
    if (!saved) return false;
    try {
      const target = typeof saved.blockId === 'string'
        ? (document.getElementById(`block-${saved.blockId}`) || document.getElementById(saved.blockId))
        : null;
      if (target) {
        target.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', block: 'start' });
        return true;
      }
      if (saved.readerRevision === readerRevision && Number.isFinite(saved.scrollRatio)) {
        const max = Math.max(0, document.documentElement.scrollHeight - innerHeight);
        scrollTo({
          top: Math.min(max, Math.max(0, saved.scrollRatio * max)),
          behavior: smooth ? 'smooth' : 'auto',
        });
        return true;
      }
    } catch (_error) {
      return false;
    }
    return false;
  };

  resumeButton.addEventListener('click', () => {
    restoreSavedPosition(savedAtLoad, true);
  });
  addEventListener('scroll', scheduleScrollUpdate, { passive: true });
  addEventListener('resize', scheduleScrollUpdate, { passive: true });
  addEventListener('beforeunload', persistProgress);
  updateProgress();

  if (!location.hash && savedAtLoad) {
    requestAnimationFrame(() => restoreSavedPosition(savedAtLoad, false));
  } else if (location.hash) {
    revealLowValueTarget(document.getElementById(location.hash.slice(1)));
  }

  const headings = [...document.querySelectorAll('article h2[id], article h3[id]')];
  const setActive = (id) => {
    tocLinks.forEach((link) => link.classList.toggle('active', link.hash === `#${id}`));
  };
  const observer = new IntersectionObserver((entries) => {
    const visible = entries.filter((entry) => entry.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
    if (visible[0]) setActive(visible[0].target.id);
  }, { rootMargin: '-10% 0px -78% 0px' });
  headings.forEach((heading) => observer.observe(heading));

  document.querySelectorAll('.mobile-nav a').forEach((link) => {
    link.addEventListener('click', () => link.closest('details').removeAttribute('open'));
  });

  const assetDialog = document.querySelector('#asset-dialog');
  const dialogContent = document.querySelector('#asset-dialog-content');
  const dialogTitle = document.querySelector('#asset-dialog-title');
  const dialogClose = document.querySelector('#close-asset-dialog');
  let lastDialogTrigger = null;

  const closeAssetDialog = () => {
    try {
      if (assetDialog.open) assetDialog.close();
    } catch (_error) {
      assetDialog.removeAttribute('open');
    }
    dialogContent.replaceChildren();
    if (lastDialogTrigger) {
      lastDialogTrigger.focus();
      lastDialogTrigger = null;
    }
  };

  const openAssetDialog = (trigger) => {
    try {
      if (typeof assetDialog.showModal !== 'function') return;
      const asset = trigger.closest('.paper-asset');
      const kind = trigger.dataset.assetKind;
      const sources = kind === 'figure'
        ? [...asset.querySelectorAll('img')].slice(0, 1)
        : [...asset.querySelectorAll('table, img')];
      if (!sources.length) return;
      dialogContent.replaceChildren(...sources.map((source) => source.cloneNode(true)));
      dialogTitle.textContent = kind === 'figure' ? 'Figure 放大' : 'Table 放大';
      lastDialogTrigger = trigger;
      assetDialog.showModal();
    } catch (_error) {
      dialogContent.replaceChildren();
    }
  };

  document.querySelectorAll('.asset-dialog-trigger').forEach((trigger) => {
    trigger.addEventListener('click', () => openAssetDialog(trigger));
  });
  dialogClose.addEventListener('click', closeAssetDialog);
  assetDialog.addEventListener('cancel', (event) => {
    event.preventDefault();
    closeAssetDialog();
  });
  assetDialog.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      closeAssetDialog();
    }
  });
  assetDialog.addEventListener('click', (event) => {
    if (event.target === assetDialog) closeAssetDialog();
  });

  const citationDialog = document.querySelector('#citation-dialog');
  const citationContent = document.querySelector('#citation-dialog-content');
  const citationClose = document.querySelector('#close-citation-dialog');
  const referenceDataNode = document.querySelector('#reference-data');
  let referenceData = {};
  let lastCitationTrigger = null;
  try {
    const payload = JSON.parse(referenceDataNode ? referenceDataNode.textContent : '{}');
    referenceData = payload && payload.contract_version === 'reader-references-v1'
      ? (payload.references || {})
      : {};
  } catch (_error) {
    referenceData = {};
  }

  const queueStorageKey = 'sr-next-reading:v1';
  const queueContract = 'sr-next-reading-v1';
  const openReadingQueue = document.querySelector('#open-reading-queue');
  const readingQueueDialog = document.querySelector('#reading-queue-dialog');
  const closeReadingQueue = document.querySelector('#close-reading-queue');
  const readingQueueItems = document.querySelector('#reading-queue-items');
  const clearReadingQueue = document.querySelector('#clear-reading-queue');
  const exportReadingQueue = document.querySelector('#export-reading-queue');
  let readingQueue = { contract_version: queueContract, items: [] };

  const normalizeKeyText = (value) => String(value || '')
    .normalize('NFKC')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim();
  const candidateKey = (entry) => {
    if (entry.doi) return `doi:${normalizeKeyText(entry.doi)}`;
    if (entry.arxiv_id) return `arxiv:${normalizeKeyText(entry.arxiv_id)}`;
    return `reference:${normalizeKeyText(entry.raw_reference)}`;
  };
  const sanitizeQueue = (value) => {
    if (!value || value.contract_version !== queueContract || !Array.isArray(value.items)) {
      return { contract_version: queueContract, items: [] };
    }
    return {
      contract_version: queueContract,
      items: value.items.filter((item) => (
        item && typeof item.candidate_key === 'string'
        && typeof item.raw_reference === 'string'
        && Array.isArray(item.source_contexts)
      )),
    };
  };
  try {
    const rawQueue = localStorage.getItem(queueStorageKey);
    readingQueue = rawQueue ? sanitizeQueue(JSON.parse(rawQueue)) : readingQueue;
  } catch (_error) {
    readingQueue = { contract_version: queueContract, items: [] };
  }
  const persistQueue = () => {
    try {
      localStorage.setItem(queueStorageKey, JSON.stringify(readingQueue));
    } catch (_error) {
      // Keep the in-memory queue usable and exportable.
    }
  };
  const updateQueueCount = () => {
    openReadingQueue.textContent = `待读 ${readingQueue.items.length}`;
  };
  const renderReadingQueue = () => {
    readingQueueItems.replaceChildren();
    if (!readingQueue.items.length) {
      const empty = document.createElement('p');
      empty.className = 'reading-queue-empty';
      empty.textContent = '还没有加入下一步阅读的文献。';
      readingQueueItems.append(empty);
      updateQueueCount();
      return;
    }
    readingQueue.items.forEach((item) => {
      const queueItem = document.createElement('article');
      queueItem.className = 'reading-queue-item';
      queueItem.textContent = '';
      const reference = document.createElement('p');
      reference.className = 'reading-queue-item-reference';
      reference.textContent = item.raw_reference;
      const metadata = document.createElement('div');
      metadata.className = 'reading-queue-item-meta';
      metadata.textContent = [item.year, item.doi, item.arxiv_id ? `arXiv:${item.arxiv_id}` : '', `${item.source_contexts.length} 个来源`]
        .filter(Boolean)
        .join(' · ');
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'reading-queue-remove';
      remove.dataset.candidateKey = item.candidate_key;
      remove.textContent = '移除';
      queueItem.append(reference, metadata, remove);
      readingQueueItems.append(queueItem);
    });
    updateQueueCount();
  };
  const addToQueue = (label, entry, blockId) => {
    const key = candidateKey(entry);
    const context = {
      paper_id: paperId,
      block_id: blockId || '',
      citation_label: label,
    };
    const existing = readingQueue.items.find((item) => item.candidate_key === key);
    if (existing) {
      const duplicate = existing.source_contexts.some((source) => (
        source.paper_id === context.paper_id
        && source.block_id === context.block_id
        && source.citation_label === context.citation_label
      ));
      if (!duplicate) existing.source_contexts.push(context);
    } else {
      readingQueue.items.push({
        candidate_key: key,
        raw_reference: entry.raw_reference || '',
        doi: entry.doi || null,
        arxiv_id: entry.arxiv_id || null,
        year: entry.year || null,
        source_contexts: [context],
      });
    }
    persistQueue();
    renderReadingQueue();
  };

  renderReadingQueue();
  citationContent.addEventListener('click', (event) => {
    const button = event.target.closest('.queue-add');
    if (!button) return;
    const label = button.dataset.reference;
    const entry = referenceData[label];
    if (!entry) return;
    addToQueue(label, entry, button.dataset.block);
    button.textContent = '已加入下一步阅读';
  });
  readingQueueItems.addEventListener('click', (event) => {
    const button = event.target.closest('.reading-queue-remove');
    if (!button) return;
    readingQueue.items = readingQueue.items.filter(
      (item) => item.candidate_key !== button.dataset.candidateKey,
    );
    persistQueue();
    renderReadingQueue();
  });
  openReadingQueue.addEventListener('click', () => {
    renderReadingQueue();
    readingQueueDialog.showModal();
  });
  const closeReadingQueueDialog = () => {
    try {
      if (readingQueueDialog.open) readingQueueDialog.close();
    } catch (_error) {
      readingQueueDialog.removeAttribute('open');
    }
    openReadingQueue.focus();
  };
  closeReadingQueue.addEventListener('click', closeReadingQueueDialog);
  readingQueueDialog.addEventListener('cancel', (event) => {
    event.preventDefault();
    closeReadingQueueDialog();
  });
  readingQueueDialog.addEventListener('click', (event) => {
    if (event.target === readingQueueDialog) closeReadingQueueDialog();
  });
  clearReadingQueue.addEventListener('click', () => {
    readingQueue = { contract_version: queueContract, items: [] };
    persistQueue();
    renderReadingQueue();
  });
  exportReadingQueue.addEventListener('click', () => {
    try {
      const blob = new Blob([JSON.stringify(readingQueue, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'scientific-reading-queue.json';
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (_error) {
      exportReadingQueue.textContent = '导出失败，请稍后重试';
    }
  });

  const closeCitationDialog = () => {
    try {
      if (citationDialog.open) citationDialog.close();
    } catch (_error) {
      citationDialog.removeAttribute('open');
    }
    citationContent.replaceChildren();
    if (lastCitationTrigger) {
      lastCitationTrigger.focus();
      lastCitationTrigger = null;
    }
  };

  const buildReferenceCard = (label, entry, blockId) => {
    const referenceCard = document.createElement('article');
    referenceCard.className = 'citation-card';
    referenceCard.textContent = '';
    const heading = document.createElement('div');
    heading.className = 'citation-card-label';
    heading.textContent = `参考文献 ${label}`;
    const rawReference = document.createElement('p');
    rawReference.className = 'citation-card-reference';
    rawReference.textContent = entry.raw_reference || '';
    const metadata = document.createElement('div');
    metadata.className = 'citation-card-meta';
    metadata.textContent = [entry.year, entry.doi, entry.arxiv_id ? `arXiv:${entry.arxiv_id}` : '']
      .filter(Boolean)
      .join(' · ');
    const add = document.createElement('button');
    add.type = 'button';
    add.className = 'citation-card-action queue-add';
    add.dataset.reference = label;
    add.dataset.block = blockId || '';
    add.textContent = '加入下一步阅读';
    referenceCard.append(heading, rawReference, metadata, add);
    return referenceCard;
  };

  document.querySelectorAll('.citation-trigger').forEach((trigger) => {
    trigger.addEventListener('click', () => {
      const labels = (trigger.dataset.references || '').split(',').filter(Boolean);
      const cards = labels
        .filter((label) => referenceData[label])
        .map((label) => buildReferenceCard(label, referenceData[label], trigger.dataset.block));
      if (!cards.length) return;
      citationContent.replaceChildren(...cards);
      lastCitationTrigger = trigger;
      citationDialog.showModal();
    });
  });
  citationClose.addEventListener('click', closeCitationDialog);
  citationDialog.addEventListener('cancel', (event) => {
    event.preventDefault();
    closeCitationDialog();
  });
  citationDialog.addEventListener('click', (event) => {
    if (event.target === citationDialog) closeCitationDialog();
  });
})();
"""


def load_highlights(path: Path) -> dict[str, tuple[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("highlights")
    if not isinstance(rows, list):
        raise ValueError("重点配置必须包含 highlights 数组")

    highlights: dict[str, tuple[str, str]] = {}
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"第 {index} 条重点不是对象")
        block_id = str(row.get("block_id", "")).strip()
        raw_kind = row.get("kind", row.get("source", ""))
        kind = normalize_highlight_kind(str(raw_kind).strip())
        reason = str(row.get("reason", "")).strip()
        if not block_id or not reason:
            raise ValueError(
                f"第 {index} 条重点必须提供 block_id、有效 kind 和非空 reason"
            )
        if block_id in highlights:
            raise ValueError(f"重点配置中 block_id 重复: {block_id}")
        highlights[block_id] = (kind, reason)
    return highlights


def previous_tag(tag: Tag) -> Tag | None:
    sibling = tag.previous_sibling
    while sibling is not None and not isinstance(sibling, Tag):
        sibling = sibling.previous_sibling
    return sibling


def next_tag(tag: Tag) -> Tag | None:
    sibling = tag.next_sibling
    while sibling is not None and not isinstance(sibling, Tag):
        sibling = sibling.next_sibling
    return sibling


def _clone_tag(value: Tag) -> Tag:
    clone = BeautifulSoup(str(value), "html.parser").find()
    if not isinstance(clone, Tag):
        raise ValueError("bilingual_block_invalid")
    return clone


def _remove_highlight_ink(value: Tag) -> None:
    for ink in value.select(".highlight-ink"):
        ink.unwrap()


def _append_english_content(soup: BeautifulSoup, target: Tag, source: Tag) -> None:
    if target.name in {"ol", "ul"}:
        if source.name == "li":
            rows = [source]
        else:
            values = [
                line.strip().removeprefix("-").strip()
                for line in source.get_text("\n", strip=True).splitlines()
                if line.strip()
            ]
            rows = []
            for value in values or [source.get_text(" ", strip=True)]:
                item = soup.new_tag("li")
                item.string = value
                rows.append(item)
        for row in rows:
            target.append(_clone_tag(row))
        return

    fragment = BeautifulSoup(source.decode_contents(), "html.parser")
    for child in list(fragment.contents):
        target.append(child)


def _swap_bilingual_layers(soup: BeautifulSoup, article: Tag) -> None:
    english_by_block: dict[str, tuple[Tag, str]] = {}
    source_nodes: list[Tag] = []
    for detail in article.select("details.source-text[data-block]"):
        block_id = detail.get("data-block", "")
        source = detail.select_one('[lang="en"]')
        if block_id and source is not None:
            english_by_block[block_id] = (source, detail.get("data-page", ""))
            source_nodes.append(detail)
    for detail in article.select("details.source-text-group"):
        for item in detail.select(".source-list > li[data-block]"):
            block_id = item.get("data-block", "")
            if block_id:
                english_by_block[block_id] = (item, item.get("data-page", ""))
        source_nodes.append(detail)

    for block in article.select(".reading-block[data-block]"):
        block_id = block.get("data-block", "")
        source_row = english_by_block.get(block_id)
        if source_row is None:
            continue
        source, page = source_row
        content = next(
            (
                child
                for child in block.children
                if isinstance(child, Tag)
                and "highlight-label" not in child.get("class", [])
                and child.name != "details"
            ),
            None,
        )
        if content is None:
            continue

        translation_content = _clone_tag(content)
        translation_content.attrs.pop("id", None)
        _remove_highlight_ink(translation_content)
        panel = soup.new_tag("div")
        panel["class"] = ["translation-panel"]
        panel["lang"] = "zh-CN"
        panel["data-block"] = block_id
        if page:
            panel["data-page"] = page
        panel["hidden"] = ""
        panel.append(translation_content)

        content.clear()
        _append_english_content(soup, content, source)
        content["class"] = [*content.get("class", []), "source-primary"]
        content["lang"] = "en"
        if "is-highlighted" in block.get("class", []):
            targets = (
                content.find_all("li", recursive=False)
                if content.name in {"ol", "ul"}
                else [content]
            )
            for target in targets:
                if not target.contents:
                    continue
                ink = soup.new_tag("span")
                ink["class"] = ["highlight-ink"]
                for child in list(target.contents):
                    ink.append(child.extract())
                target.append(ink)

        block.append(panel)
        block["tabindex"] = "0"
        block["aria-expanded"] = "false"
        block["aria-label"] = "点击展开中文翻译"

    for node in source_nodes:
        node.decompose()

    for heading in article.select("h2.source-primary[id], h3.source-primary[id]"):
        link = soup.select_one(f'.toc a[href="#{heading.get("id", "")}"]')
        if link is None:
            continue
        marks = link.select_one(".toc-marks")
        link.clear()
        fragment = BeautifulSoup(heading.decode_contents(), "html.parser")
        label = soup.new_tag("span")
        label["class"] = ["toc-label"]
        for child in list(fragment.contents):
            label.append(child)
        link.append(label)
        if marks is not None:
            link.append(marks)


def canonical_heading(value: str) -> str:
    normalized = re.sub(
        r"^\s*(?:(?:\d+(?:\.\d+)*)|(?:[ivxlcdm]+))[.)]?\s+",
        "",
        value.casefold(),
    )
    return re.sub(r"[^a-z]+", " ", normalized).strip()


def _render_safe_inline_scripts(soup: BeautifulSoup, article: Tag) -> None:
    pattern = re.compile(r"<(sup|sub)>([^<>]{1,64})</\1>", re.I)
    for container in article.select(".source-primary"):
        for node in list(container.find_all(string=True)):
            value = str(node)
            matches = list(pattern.finditer(value))
            if not matches:
                continue
            replacement: list[NavigableString | Tag] = []
            cursor = 0
            for match in matches:
                if match.start() > cursor:
                    replacement.append(NavigableString(value[cursor:match.start()]))
                script = soup.new_tag(match.group(1).casefold())
                script.string = match.group(2)
                replacement.append(script)
                cursor = match.end()
            if cursor < len(value):
                replacement.append(NavigableString(value[cursor:]))
            node.replace_with(*replacement)


def low_value_section_kind(value: str) -> str | None:
    heading = canonical_heading(value)
    if heading in {"references", "bibliography"}:
        return "references"
    if heading in {"acknowledgements", "acknowledgments"}:
        return "acknowledgements"
    if heading in {
        "author contributions",
        "competing interests",
        "conflict of interest",
        "ethics statement",
        "data availability",
        "supplementary information",
    }:
        return "administrative"
    return None


def _direct_heading(node: Tag) -> Tag | None:
    if node.name in {"h2", "h3"}:
        return node
    return node.select_one(":scope > h2, :scope > h3")


def _make_low_value_region(
    soup: BeautifulSoup,
    nodes: list[Tag],
    *,
    kind: str,
    label: str,
    region_id: str,
) -> None:
    if not nodes:
        return
    details = soup.new_tag("details", id=region_id)
    details["class"] = ["low-value-region"]
    details["data-kind"] = kind
    summary = soup.new_tag("summary")
    summary.string = f"{label} · {len(nodes)}项"
    content = soup.new_tag("div")
    content["class"] = ["low-value-content"]
    nodes[0].insert_before(details)
    details.append(summary)
    details.append(content)
    for node in nodes:
        content.append(node.extract())


def _fold_low_value_regions(soup: BeautifulSoup, article: Tag) -> None:
    label_by_kind = {
        "references": "参考文献",
        "acknowledgements": "致谢",
        "administrative": "声明与附加信息",
    }
    substantive = {
        "abstract",
        "introduction",
        "background",
        "related work",
    }
    frontmatter_patterns = (
        re.compile(r"\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b", re.I),
        re.compile(
            r"\b(?:department|university|institute|laboratory|college|school|faculty|corresponding author)\b",
            re.I,
        ),
        re.compile(r"\b(?:copyright|all rights reserved|preprint)\b", re.I),
        re.compile(
            r"\b(?:grants? permission|permission to reproduce|provided proper attribution)\b",
            re.I,
        ),
    )
    title_node = article.find("h1")
    title_text = title_node.get_text(" ", strip=True).casefold() if title_node else ""

    def is_frontmatter_candidate(node: Tag) -> bool:
        text = node.get_text(" ", strip=True)
        source = node.select_one(".source-primary")
        source_text = source.get_text(" ", strip=True).casefold() if source else ""
        return any(pattern.search(text) for pattern in frontmatter_patterns) or (
            bool(title_text) and source_text == title_text
        )

    children = [child for child in article.children if isinstance(child, Tag)]
    boundary = next(
        (
            index
            for index, node in enumerate(children)
            if (heading := _direct_heading(node)) is not None
            and canonical_heading(heading.get_text(" ", strip=True)) in substantive
        ),
        None,
    )
    if boundary is not None:
        candidates = [
            node
            for node in children[:boundary]
            if "reading-block" in node.get("class", [])
            and is_frontmatter_candidate(node)
        ]
        if candidates:
            _make_low_value_region(
                soup,
                candidates,
                kind="frontmatter",
                label="题名页信息",
                region_id="low-value-frontmatter",
            )

    children = [child for child in article.children if isinstance(child, Tag)]
    index = 0
    serial = 0
    while index < len(children):
        heading = _direct_heading(children[index])
        kind = (
            low_value_section_kind(heading.get_text(" ", strip=True))
            if heading is not None
            else None
        )
        if kind is None:
            index += 1
            continue
        end = index + 1
        while end < len(children) and _direct_heading(children[end]) is None:
            end += 1
        serial += 1
        _make_low_value_region(
            soup,
            children[index:end],
            kind=kind,
            label=label_by_kind[kind],
            region_id=f"low-value-{kind}-{serial}",
        )
        children = [child for child in article.children if isinstance(child, Tag)]
        index += 1


@dataclass(frozen=True)
class ReferenceEntry:
    label: str
    raw_reference: str
    doi: str | None
    arxiv_id: str | None
    year: str | None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "label": self.label,
            "raw_reference": self.raw_reference,
            "doi": self.doi,
            "arxiv_id": self.arxiv_id,
            "year": self.year,
        }


def extract_numbered_references(article: Tag) -> dict[str, ReferenceEntry]:
    entries: dict[str, ReferenceEntry] = {}
    blocks = list(article.select(".reference-block"))
    for block in article.select(
        'details.low-value-region[data-kind="references"] .reading-block'
    ):
        if block not in blocks:
            blocks.append(block)
    for block in blocks:
        source = block.select_one(".source-primary")
        raw_block = (source or block).get_text(" ", strip=True)
        chunks = re.split(r"(?=\[\d+\]\s*)", raw_block)
        for raw in chunks:
            raw = raw.strip()
            match = re.match(r"^\s*\[?(\d+)\]?[.)]?\s*(.+)$", raw)
            if match is None:
                continue
            label = match.group(1)
            if label in entries:
                continue
            doi_match = re.search(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", raw, re.I)
            doi = doi_match.group(0).rstrip(".,;)").casefold() if doi_match else None
            arxiv_match = re.search(
                r"\barxiv\s*:\s*(\d{4}\.\d{4,5}(?:v\d+)?)\b",
                raw,
                re.I,
            )
            year_match = re.search(r"\b(?:19|20)\d{2}\b", raw)
            entries[label] = ReferenceEntry(
                label=label,
                raw_reference=raw,
                doi=doi,
                arxiv_id=arxiv_match.group(1) if arxiv_match else None,
                year=year_match.group(0) if year_match else None,
            )
    return entries


def _expand_reference_labels(value: str) -> list[str]:
    labels: list[str] = []
    for part in re.split(r"\s*,\s*", value):
        range_match = re.fullmatch(r"(\d+)\s*[-–—]\s*(\d+)", part)
        if range_match is None:
            if part.isdigit():
                labels.append(str(int(part)))
            continue
        start, end = (int(range_match.group(1)), int(range_match.group(2)))
        if start <= end and end - start <= 50:
            labels.extend(str(number) for number in range(start, end + 1))
    return list(dict.fromkeys(labels))


def decorate_numeric_citations(
    soup: BeautifulSoup,
    article: Tag,
    references: dict[str, ReferenceEntry],
) -> None:
    if not references:
        return
    citation_pattern = re.compile(
        r"\[(\d+(?:\s*(?:,|[-–—])\s*\d+)*)\]"
    )
    for primary in article.select(".source-primary"):
        if primary.find_parent(
            "details", class_="low-value-region", attrs={"data-kind": "references"}
        ):
            continue
        block = primary.find_parent(class_="reading-block")
        if block is None:
            continue
        for node in list(primary.descendants):
            if not isinstance(node, NavigableString) or not node.strip():
                continue
            parent = node.parent
            if parent is None or parent.name in {"code", "pre", "math", "a", "button"}:
                continue
            matches = list(citation_pattern.finditer(str(node)))
            if not matches:
                continue
            replacement: list[Tag | NavigableString] = []
            cursor = 0
            for match in matches:
                labels = _expand_reference_labels(match.group(1))
                if not labels or any(label not in references for label in labels):
                    continue
                if match.start() > cursor:
                    replacement.append(NavigableString(str(node)[cursor:match.start()]))
                trigger = soup.new_tag("button", type="button")
                trigger["class"] = ["citation-trigger"]
                trigger["data-references"] = ",".join(labels)
                trigger["data-block"] = block.get("data-block", "")
                trigger["aria-haspopup"] = "dialog"
                trigger["aria-controls"] = "citation-dialog"
                trigger.string = match.group(0)
                replacement.append(trigger)
                cursor = match.end()
            if not replacement:
                continue
            if cursor < len(str(node)):
                replacement.append(NavigableString(str(node)[cursor:]))
            node.replace_with(*replacement)


def build_reader(
    source: Path,
    output: Path,
    highlights: dict[str, tuple[str, str]],
    *,
    guide: dict[str, list[dict[str, object]]],
    paper_id: str,
    reader_revision: str,
) -> None:
    if not isinstance(paper_id, str) or not paper_id.strip():
        raise ValueError("paper_id_required")
    if (
        not isinstance(reader_revision, str)
        or re.fullmatch(r"[0-9a-f]{64}", reader_revision) is None
    ):
        raise ValueError("reader_revision_invalid")
    highlights = {
        block_id: (normalize_highlight_kind(kind), reason)
        for block_id, (kind, reason) in highlights.items()
    }
    soup = BeautifulSoup(source.read_text(encoding="utf-8"), "html.parser")
    if soup.head is None:
        raise ValueError("输入 HTML 缺少 head")
    charset = soup.head.select_one("meta[charset]")
    if charset is None:
        charset = soup.new_tag("meta", charset="utf-8")
        soup.head.insert(0, charset)
    else:
        charset["charset"] = "utf-8"
    original_main = soup.select_one("main.paper")
    article = soup.find("article")
    metadata = soup.select_one(".paper-meta")
    toc = soup.select_one(".toc")
    if original_main is None or article is None or metadata is None or toc is None:
        raise ValueError("输入 HTML 不符合现有 MinerU reader 结构")

    source_details = list(article.select("details.source-text[data-block]"))
    if not source_details:
        raise ValueError("输入 HTML 没有可追溯的双语段落")
    available_blocks = {detail.get("data-block", "") for detail in source_details}
    unknown_blocks = sorted(set(highlights) - available_blocks)
    if unknown_blocks:
        raise ValueError(f"重点配置引用了不存在的 block_id: {', '.join(unknown_blocks)}")
    guide_labels = {
        "research_question": "研究问题",
        "key_methods": "关键方法",
        "core_results": "核心结果",
        "limitations": "局限性",
    }
    if not isinstance(guide, dict) or set(guide) != set(guide_labels):
        raise ValueError("reading_guide_invalid")
    for category in guide_labels:
        entries = guide[category]
        if not isinstance(entries, list):
            raise ValueError("reading_guide_invalid")
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {
                "text", "source_block_ids"
            }:
                raise ValueError("guide_entry_invalid")
            text = entry["text"]
            block_ids = entry["source_block_ids"]
            if (
                not isinstance(text, str)
                or not text.strip()
                or not isinstance(block_ids, list)
                or not block_ids
                or any(block_id not in available_blocks for block_id in block_ids)
            ):
                raise ValueError("guide_entry_invalid")
    for detail in source_details:
        content = previous_tag(detail)
        if content is None:
            continue
        block_id = detail.get("data-block", "")
        wrapper = soup.new_tag("section")
        wrapper["class"] = ["reading-block"]
        wrapper["data-block"] = block_id
        wrapper["id"] = f"block-{block_id}"
        content.wrap(wrapper)
        wrapper.append(detail.extract())
        if block_id in highlights:
            kind, reason = highlights[block_id]
            wrapper["class"].append("is-highlighted")
            wrapper["data-highlight-kind"] = kind
            label = soup.new_tag("div")
            label["class"] = ["highlight-label"]
            label["data-reason"] = reason
            label["tabindex"] = "0"
            labels = {
                "result": "核心结果/结论 · ",
                "method": "方法/证据 · ",
            }
            label.string = labels[kind] + reason
            wrapper.insert(0, label)
            highlight_targets = (
                content.find_all("li", recursive=False)
                if content.name in {"ol", "ul"}
                else [content]
            )
            for target in highlight_targets:
                if not target.contents:
                    continue
                ink = soup.new_tag("span")
                ink["class"] = ["highlight-ink"]
                for child in list(target.contents):
                    ink.append(child.extract())
                target.append(ink)

    for block in article.select(".reading-block.is-highlighted"):
        heading = block.find_previous(["h2", "h3"])
        if heading is not None and "focus-heading" not in heading.get("class", []):
            heading["class"] = [*heading.get("class", []), "focus-heading"]
        for neighbor in (previous_tag(block), next_tag(block)):
            if (
                neighbor is not None
                and neighbor.name == "figure"
                and "paper-asset" in neighbor.get("class", [])
                and "focus-near-highlight" not in neighbor.get("class", [])
            ):
                neighbor["class"].append("focus-near-highlight")

    list_sequences: list[list[Tag]] = []
    current_sequence: list[Tag] = []
    current_list_kind: str | None = None
    for node in [child for child in article.children if isinstance(child, Tag)]:
        classes = node.get("class", [])
        content_tags = [
            child
            for child in node.children
            if isinstance(child, Tag)
            and "highlight-label" not in child.get("class", [])
            and child.name != "details"
        ]
        list_content = content_tags[0] if content_tags else None
        detail = node.select_one("details.source-text")
        source_paragraph = (
            detail.select_one('p[lang="en"]') if detail else None
        )
        list_items = (
            list_content.find_all("li", recursive=False)
            if list_content is not None
            and list_content.name in {"ol", "ul"}
            else []
        )
        is_short_list = (
            "reading-block" in classes
            and list_content is not None
            and list_content.name in {"ol", "ul"}
            and 1 <= len(list_items) <= 3
            and len(list_content.get_text(" ", strip=True)) <= 320
            and source_paragraph is not None
            and len(source_paragraph.get_text(" ", strip=True)) <= 320
        )
        if (
            is_short_list
            and current_sequence
            and current_list_kind != list_content.name
        ):
            if len(current_sequence) >= 3:
                list_sequences.append(current_sequence)
            current_sequence = []
        if is_short_list:
            current_sequence.append(node)
            current_list_kind = list_content.name
        else:
            if len(current_sequence) >= 3:
                list_sequences.append(current_sequence)
            current_sequence = []
            current_list_kind = None
    if len(current_sequence) >= 3:
        list_sequences.append(current_sequence)

    for sequence in list_sequences:
        group = soup.new_tag("section")
        group["class"] = ["reading-group"]
        if any("is-highlighted" in block.get("class", []) for block in sequence):
            group["class"].append("has-highlight")
        sequence[0].insert_before(group)

        source_list = soup.new_tag("ol")
        source_list["class"] = ["source-list"]
        source_list["lang"] = "en"
        block_ids: list[str] = []
        pages: list[str] = []
        for block in sequence:
            block_id = block.get("data-block", "")
            detail = block.select_one("details.source-text")
            source_paragraph = detail.select_one('p[lang="en"]') if detail else None
            if block_id:
                block_ids.append(block_id)
            if detail and detail.get("data-page"):
                pages.append(detail["data-page"])
            if source_paragraph is not None:
                item = soup.new_tag("li")
                item["data-block"] = block_id
                if detail and detail.get("data-page"):
                    item["data-page"] = detail["data-page"]
                source_fragment = BeautifulSoup(source_paragraph.decode_contents(), "html.parser")
                for child in list(source_fragment.contents):
                    item.append(child)
                source_list.append(item)
            if detail is not None:
                detail.decompose()
            group.append(block.extract())

        grouped_detail = soup.new_tag("details")
        grouped_detail["class"] = ["source-text", "source-text-group"]
        grouped_detail["data-blocks"] = ",".join(block_ids)
        grouped_detail["data-pages"] = ",".join(dict.fromkeys(pages))
        summary = soup.new_tag("summary")
        page_label = f"p{'–'.join(dict.fromkeys(pages))}" if pages else ""
        block_label = f"{block_ids[0]}–{block_ids[-1]}" if block_ids else ""
        summary.string = f"英文原文 · {page_label} {block_label} · {len(block_ids)} 条"
        grouped_detail.append(summary)
        grouped_detail.append(source_list)
        group.append(grouped_detail)

    _swap_bilingual_layers(soup, article)
    _render_safe_inline_scripts(soup, article)
    _fold_low_value_regions(soup, article)
    references = extract_numbered_references(article)
    decorate_numeric_citations(soup, article, references)

    section_highlights: dict[str, set[str]] = {}
    for block in article.select(".reading-block.is-highlighted"):
        heading = block.find_previous(
            lambda candidate: isinstance(candidate, Tag)
            and candidate.name in {"h2", "h3"}
            and bool(candidate.get("id"))
        )
        section_id = heading.get("id") if heading else None
        kind = block.get("data-highlight-kind")
        if section_id and kind:
            section_highlights.setdefault(section_id, set()).add(kind)

    section_assets: dict[str, set[str]] = {}
    for asset in article.select("figure.paper-asset"):
        progress_anchor = asset.find_previous(
            lambda candidate: isinstance(candidate, Tag)
            and (
                (
                    candidate.name in {"h2", "h3"}
                    and bool(candidate.get("id"))
                )
                or (
                    "reading-block" in candidate.get("class", [])
                    and bool(candidate.get("id"))
                )
            )
        )
        if progress_anchor is not None:
            asset["data-progress-anchor"] = progress_anchor["id"]
        if (
            asset.select_one(".reading-block.is-highlighted") is not None
            and "focus-near-highlight" not in asset.get("class", [])
        ):
            asset["class"].append("focus-near-highlight")
        heading = asset.find_previous(
            lambda candidate: isinstance(candidate, Tag)
            and candidate.name in {"h2", "h3"}
            and bool(candidate.get("id"))
        )
        section_id = heading.get("id") if heading else None
        asset_kind = (
            "table" if "table" in asset.get("class", []) else "figure"
        )
        if section_id:
            section_assets.setdefault(section_id, set()).add(asset_kind)

        asset_id = str(asset.get("data-asset", "图表"))
        if asset_kind == "figure":
            image = asset.find("img")
            if image is not None:
                trigger = soup.new_tag("button", type="button")
                trigger["class"] = [
                    "asset-dialog-trigger",
                    "asset-image-trigger",
                ]
                trigger["data-asset-kind"] = "figure"
                trigger["aria-controls"] = "asset-dialog"
                trigger["aria-haspopup"] = "dialog"
                trigger["aria-label"] = f"放大图 {asset_id}"
                image.wrap(trigger)
        else:
            media = asset.find(["table", "img"])
            if media is not None:
                trigger = soup.new_tag("button", type="button")
                trigger["class"] = [
                    "asset-dialog-trigger",
                    "asset-table-trigger",
                ]
                trigger["data-asset-kind"] = "table"
                trigger["aria-controls"] = "asset-dialog"
                trigger["aria-haspopup"] = "dialog"
                trigger.string = "放大表格"
                media.insert_before(trigger)

    source_order = ("result", "method")
    source_labels = {
        "result": "核心结果/结论", "method": "方法/证据",
    }
    source_classes = {
        "result": "result", "method": "method",
    }
    asset_order = ("figure", "table")
    asset_labels = {"figure": "图", "table": "表"}
    for link in toc.select('a[href^="#"]'):
        section_id = link.get("href", "").removeprefix("#")
        label = soup.new_tag("span")
        label["class"] = ["toc-label"]
        label.string = link.get_text(" ", strip=True)
        link.clear()
        link.append(label)
        sources = [source for source in source_order if source in section_highlights.get(section_id, set())]
        asset_kinds = [
            kind
            for kind in asset_order
            if kind in section_assets.get(section_id, set())
        ]
        if not sources and not asset_kinds:
            continue
        marks = soup.new_tag("span")
        marks["class"] = ["toc-marks"]
        marks["role"] = "img"
        marks["aria-label"] = "、".join(
            [source_labels[source] for source in sources]
            + [asset_labels[kind] for kind in asset_kinds]
        )
        marks["title"] = marks["aria-label"]
        for source in sources:
            dot = soup.new_tag("span")
            dot["class"] = ["toc-mark", source_classes[source]]
            dot["title"] = source_labels[source]
            dot["aria-hidden"] = "true"
            marks.append(dot)
        for kind in asset_kinds:
            asset_mark = soup.new_tag("span")
            asset_mark["class"] = ["toc-mark", kind]
            asset_mark["title"] = asset_labels[kind]
            asset_mark["aria-hidden"] = "true"
            asset_mark.string = "F" if kind == "figure" else "T"
            marks.append(asset_mark)
        link.append(marks)

    title = article.find("h1")
    title_text = title.get_text(" ", strip=True) if title else soup.title.get_text(strip=True)
    original_title = (
        title.find_next_sibling("p", class_="original-title")
        if title
        else None
    )
    original_title_text = original_title.get_text(" ", strip=True) if original_title else ""
    if original_title is not None:
        original_title.extract()
    if title is not None:
        title.extract()
    author_block = article.select_one('.reading-block[data-block="S001"]')
    if author_block is not None:
        author_block["class"].append("frontmatter-source")

    body = soup.body
    body.clear()
    body["class"] = ["periodical-first"]
    body["data-paper-id"] = paper_id.strip()
    body["data-reader-revision"] = reader_revision
    body["data-language"] = "en"
    body["data-reading"] = "full"
    progress = soup.new_tag("div")
    progress["class"] = ["reading-progress"]
    progress["aria-hidden"] = "true"
    body.append(progress)

    shell = soup.new_tag("div")
    shell["class"] = ["reader-shell"]
    body.append(shell)

    sidebar = soup.new_tag("aside")
    sidebar["class"] = ["reader-sidebar"]
    mark = soup.new_tag("div")
    mark["class"] = ["reader-mark"]
    mark.append("Scientific Reader")
    mark_title = soup.new_tag("strong")
    mark_title.string = "期刊正文阅读"
    mark.append(mark_title)
    sidebar.append(mark)

    sidebar_guide = soup.new_tag("section")
    sidebar_guide["class"] = ["sidebar-guide"]
    sidebar_guide["aria-label"] = "阅读导览"
    guide_heading = soup.new_tag("div")
    guide_heading["class"] = ["guide-heading"]
    guide_heading.string = "阅读导览"
    sidebar_guide.append(guide_heading)
    guide_list = soup.new_tag("div")
    guide_list["class"] = ["sidebar-guide-list"]
    sidebar_guide.append(guide_list)
    for category, category_label in guide_labels.items():
        item = soup.new_tag("section")
        item["class"] = ["sidebar-guide-item", f"guide-{category}"]
        details = soup.new_tag("details")
        summary = soup.new_tag("summary")
        summary_label = soup.new_tag("strong")
        summary_label.string = category_label
        summary.append(summary_label)
        entries = guide[category]
        preview = soup.new_tag("span")
        preview["class"] = ["sidebar-guide-preview"]
        preview.string = (
            str(entries[0]["text"]).strip()
            if entries
            else "原文未明确说明"
        )
        summary.append(preview)
        details.append(summary)
        content = soup.new_tag("div")
        content["class"] = ["sidebar-guide-content"]
        if entries:
            entry_list = soup.new_tag("ul")
            entry_list["class"] = ["guide-list"]
            for entry in entries:
                entry_item = soup.new_tag("li")
                entry_item["class"] = ["guide-entry"]
                entry_item.string = str(entry["text"]).strip()
                entry_list.append(entry_item)
            content.append(entry_list)
        else:
            empty = soup.new_tag("p")
            empty["class"] = ["guide-empty"]
            empty.string = "原文未明确说明"
            content.append(empty)
        details.append(content)
        item.append(details)
        if entries:
            jump = soup.new_tag(
                "a", href=f'#block-{entries[0]["source_block_ids"][0]}'
            )
            jump["class"] = ["sidebar-guide-jump"]
            jump.string = "定位原文"
            item.append(jump)
        guide_list.append(item)
    sidebar.append(sidebar_guide)
    sidebar.append(toc.extract())
    shell.append(sidebar)

    main = soup.new_tag("main")
    main["class"] = ["reader-main"]
    shell.append(main)

    mobile_nav = soup.new_tag("details")
    mobile_nav["class"] = ["mobile-nav"]
    mobile_summary = soup.new_tag("summary")
    mobile_summary.string = "导读与目录"
    mobile_nav.append(mobile_summary)
    mobile_panel = soup.new_tag("div")
    mobile_panel["class"] = ["mobile-nav-panel"]
    mobile_panel.append(
        BeautifulSoup(str(sidebar_guide), "html.parser").section
    )
    mobile_panel.append(
        BeautifulSoup(str(sidebar.select_one(".toc")), "html.parser").nav
    )
    mobile_nav.append(mobile_panel)
    main.append(mobile_nav)

    toolbar = BeautifulSoup(
        '<div class="reader-toolbar"><div class="toolbar-primary">'
        '<button id="toggle-sidebar" class="sidebar-toggle" type="button" aria-expanded="true">目录</button>'
        '<button id="resume-reading" class="resume-reading" type="button" disabled hidden>回到上次</button>'
        '<button id="open-reading-queue" class="reading-queue-open" type="button">待读 0</button></div>'
        '<div class="toolbar-controls">'
        '<div class="control-group language-controls" role="group" aria-label="语言">'
        '<button type="button" data-language="en" aria-pressed="true">英文</button>'
        '<button type="button" data-language="bilingual" aria-pressed="false">中英</button></div>'
        '<div class="control-group reading-controls" role="group" aria-label="阅读模式">'
        '<button type="button" data-reading="full" aria-pressed="true">全文</button>'
        '<button type="button" data-reading="clean" aria-pressed="false">无标记</button>'
        '<button type="button" data-reading="focus" aria-pressed="false">重点</button>'
        '</div></div></div>',
        "html.parser",
    ).div
    main.append(toolbar)

    card = soup.new_tag("section")
    card["class"] = ["paper-card"]
    main.append(card)
    hero = soup.new_tag("header")
    hero["class"] = ["paper-hero"]
    hero_title = soup.new_tag("h1")
    hero_title.string = title_text
    hero.append(hero_title)
    if original_title_text:
        subtitle = soup.new_tag("div")
        subtitle["class"] = ["original-title"]
        subtitle.string = original_title_text
        hero.append(subtitle)
    hero.append(metadata.extract())
    card.append(hero)
    card.append(article.extract())

    asset_dialog = soup.new_tag("dialog", id="asset-dialog")
    asset_dialog["aria-labelledby"] = "asset-dialog-title"
    dialog_panel = soup.new_tag("section")
    dialog_panel["class"] = ["asset-dialog-panel"]
    dialog_header = soup.new_tag("header")
    dialog_header["class"] = ["asset-dialog-header"]
    dialog_title = soup.new_tag("span", id="asset-dialog-title")
    dialog_title.string = "图表放大"
    dialog_header.append(dialog_title)
    dialog_close = soup.new_tag("button", id="close-asset-dialog", type="button")
    dialog_close["class"] = ["asset-dialog-close"]
    dialog_close.string = "关闭"
    dialog_header.append(dialog_close)
    dialog_panel.append(dialog_header)
    dialog_content = soup.new_tag("div", id="asset-dialog-content")
    dialog_content["class"] = ["asset-dialog-content"]
    dialog_panel.append(dialog_content)
    asset_dialog.append(dialog_panel)
    body.append(asset_dialog)

    citation_dialog = soup.new_tag("dialog", id="citation-dialog")
    citation_dialog["aria-labelledby"] = "citation-dialog-title"
    citation_panel = soup.new_tag("section")
    citation_panel["class"] = ["citation-dialog-panel"]
    citation_header = soup.new_tag("header")
    citation_header["class"] = ["citation-dialog-header"]
    citation_title = soup.new_tag("span", id="citation-dialog-title")
    citation_title.string = "引用文献"
    citation_header.append(citation_title)
    citation_close = soup.new_tag(
        "button", id="close-citation-dialog", type="button"
    )
    citation_close["class"] = ["asset-dialog-close"]
    citation_close.string = "关闭"
    citation_header.append(citation_close)
    citation_panel.append(citation_header)
    citation_content = soup.new_tag("div", id="citation-dialog-content")
    citation_content["class"] = ["citation-dialog-content"]
    citation_panel.append(citation_content)
    citation_dialog.append(citation_panel)
    body.append(citation_dialog)

    queue_dialog = soup.new_tag("dialog", id="reading-queue-dialog")
    queue_dialog["aria-labelledby"] = "reading-queue-title"
    queue_panel = soup.new_tag("section")
    queue_panel["class"] = ["reading-queue-panel"]
    queue_header = soup.new_tag("header")
    queue_header["class"] = ["citation-dialog-header"]
    queue_title = soup.new_tag("span", id="reading-queue-title")
    queue_title.string = "下一步阅读"
    queue_header.append(queue_title)
    queue_close = soup.new_tag("button", id="close-reading-queue", type="button")
    queue_close["class"] = ["asset-dialog-close"]
    queue_close.string = "关闭"
    queue_header.append(queue_close)
    queue_panel.append(queue_header)
    queue_items = soup.new_tag("div", id="reading-queue-items")
    queue_items["class"] = ["reading-queue-items"]
    queue_panel.append(queue_items)
    queue_actions = soup.new_tag("footer")
    queue_actions["class"] = ["reading-queue-actions"]
    clear_queue = soup.new_tag("button", id="clear-reading-queue", type="button")
    clear_queue.string = "清空"
    export_queue = soup.new_tag("button", id="export-reading-queue", type="button")
    export_queue.string = "导出 JSON"
    submit_queue = soup.new_tag("button", id="submit-reading-queue", type="button")
    submit_queue["disabled"] = ""
    submit_queue["title"] = "下一阶段接通 DSH"
    submit_queue.string = "交给 DSH 处理 · 下一阶段接通"
    queue_actions.extend([clear_queue, export_queue, submit_queue])
    queue_panel.append(queue_actions)
    queue_dialog.append(queue_panel)
    body.append(queue_dialog)

    reference_data = soup.new_tag("div", id="reference-data")
    reference_data["hidden"] = ""
    reference_payload = {
        "contract_version": "reader-references-v1",
        "references": {
            label: entry.to_dict()
            for label, entry in sorted(
                references.items(), key=lambda item: int(item[0])
            )
        },
    }
    reference_data.string = json.dumps(
        reference_payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("<", "\\u003c")
    body.append(reference_data)

    if soup.style:
        soup.style.string = CSS
    else:
        style = soup.new_tag("style")
        style.string = CSS
        soup.head.append(style)
    script = soup.new_tag("script")
    script.string = SCRIPT
    body.append(script)
    soup.title.string = f"{title_text} · 期刊正文阅读"

    output.write_text("<!doctype html>\n" + str(soup), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="生成离线单文件全文精读 HTML")
    parser.add_argument("source", type=Path, help="基础双语 reader.html")
    parser.add_argument("output", type=Path, help="输出 HTML")
    parser.add_argument("--highlights", type=Path, required=True, help="重点配置 JSON")
    parser.add_argument("--guide", type=Path, required=True, help="阅读导览 JSON")
    parser.add_argument("--paper-id", required=True, help="稳定文献 ID")
    parser.add_argument(
        "--reader-revision",
        required=True,
        help="64 位小写十六进制阅读器修订值",
    )
    args = parser.parse_args()
    highlights = load_highlights(args.highlights)
    guide_payload = json.loads(args.guide.read_text(encoding="utf-8"))
    guide = guide_payload.get("guide", guide_payload)
    build_reader(
        args.source,
        args.output,
        highlights,
        guide=guide,
        paper_id=args.paper_id,
        reader_revision=args.reader_revision,
    )


if __name__ == "__main__":
    main()
