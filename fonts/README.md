# 字体

内置 10 款字体。字体文件和对应 SIL OFL 1.1 许可一起分发，浏览器预览与视频渲染使用同一文件。

| 分类 | 编辑器中的字体 | 来源 | 许可文件 |
| --- | --- | --- | --- |
| 黑体 | 黑体（思源）、黑体 · 粗体（思源）、黑体 · 特粗（思源） | [思源黑体](https://github.com/adobe-fonts/source-han-sans) | LICENSE-SourceHanSans.txt |
| 宋体 | 宋体（思源）、宋体 · 粗体（思源） | [思源宋体](https://github.com/adobe-fonts/source-han-serif) | LICENSE-SourceHanSerif.txt |
| 楷体 | 楷体（霞鹜文楷） | [霞鹜文楷](https://github.com/lxgw/LxgwWenKai) | LICENSE-LXGWWenKai.txt |
| 仿宋 | 仿宋（朱雀仿宋） | [朱雀仿宋](https://github.com/TrionesType/zhuque) | LICENSE-ZhuqueFangsong.txt |
| 圆体 | 圆体（寒蝉全圆体） | [寒蝉全圆体](https://github.com/Warren2060/ChillRound) | LICENSE-ChillRound.txt |
| 其他 | 站酷小薇体 | [Google Fonts 源文件](https://github.com/google/fonts/tree/main/ofl/zcoolxiaowei) | LICENSE-zcoolxiaowei.txt |
| 其他 | 站酷快乐体 | [Google Fonts 源文件](https://github.com/google/fonts/tree/main/ofl/zcoolkuaile) | LICENSE-zcoolkuaile.txt |

新增字体的固定版本下载地址、文件大小和 SHA-256 校验值记录在 `sources.json`；字体文件保持上游原样。朱雀仿宋等字体缺少的个别粤语字，由思源黑体回退显示。浏览器仅加载当前文字所用字体及回退字体，出片也只复制本次使用的字体，避免完整字体库重复占用每条成片的空间。

用户上传的 TTF / OTF 字体存放在 `data/fonts/`，不会提交到 Git。文件内容校验后以 SHA-256 标识存放，字体名称从 OpenType name 表读取；删除字体前检查已保存的文字、字幕引用以及正在执行的任务。
