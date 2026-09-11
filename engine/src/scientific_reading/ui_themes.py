"""工作台与 Reader 共用的预设配色。"""

THEMES = (
    {"id": "paper", "label": "暖纸", "canvas": "#f3f1eb", "paper": "#fffef9",
     "ink": "#252822", "muted": "#6e726a", "line": "#d9d6ca", "accent": "#405f54",
     "sidebar": "#ebe8df", "hover": "#e9eee8", "scheme": "light"},
    {"id": "light", "label": "纯白", "canvas": "#f3f5f7", "paper": "#ffffff",
     "ink": "#20252b", "muted": "#596470", "line": "#dce1e6", "accent": "#285b8f",
     "sidebar": "#edf1f5", "hover": "#e8eef6", "scheme": "light"},
    {"id": "dark", "label": "深墨", "canvas": "#161b20", "paper": "#20272e",
     "ink": "#e4eaf0", "muted": "#a9b4be", "line": "#48535e", "accent": "#9acbb8",
     "sidebar": "#1b2228", "hover": "#2b3c38", "scheme": "dark"},
    {"id": "mist", "label": "雾蓝", "canvas": "#eaf0f2", "paper": "#f8fbfb",
     "ink": "#243b45", "muted": "#5b747e", "line": "#cbdadc", "accent": "#366e7a",
     "sidebar": "#dde8eb", "hover": "#dce9e9", "scheme": "light"},
)


def preset(value):
    # 旧版色值不再成为自定义选项；可识别的预设色沿用，其余回到暖纸。
    return next((theme for theme in THEMES if value in (theme["id"], theme["accent"])), THEMES[0])
